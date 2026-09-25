import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import {
  DEFAULT_LOCALE,
  NAMESPACES,
  SUPPORTED_LOCALES,
} from '../src/i18n/locales.js';

const isBranch = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const valueType = (value) => {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  return typeof value === 'object' ? 'object' : typeof value;
};

const flattenEntries = (value, prefix = '', includeBranches = false) => {
  if (!isBranch(value)) return prefix ? [[prefix, value]] : [];

  const entries = prefix && includeBranches ? [[prefix, value]] : [];
  return entries.concat(
    Object.keys(value)
      .sort()
      .flatMap((key) => {
        const nextPrefix = prefix ? `${prefix}.${key}` : key;
        return isBranch(value[key])
          ? flattenEntries(value[key], nextPrefix, includeBranches)
          : [[nextPrefix, value[key]]];
      }),
  );
};

export const flattenKeys = (value, prefix = '') =>
  flattenEntries(value, prefix).map(([key]) => key);

export const validateLocaleTree = (reference, candidate) => {
  const referenceEntries = new Map(flattenEntries(reference));
  const candidateEntries = new Map(flattenEntries(candidate));
  const referenceNodes = new Map(flattenEntries(reference, '', true));
  const candidateNodes = new Map(flattenEntries(candidate, '', true));
  const missing = [...referenceEntries.keys()]
    .filter((key) => !candidateEntries.has(key))
    .map((key) => `missing:${key}`);
  const extra = [...candidateEntries.keys()]
    .filter((key) => !referenceEntries.has(key))
    .map((key) => `extra:${key}`);
  const blank = [...referenceEntries.keys()]
    .filter((key) => {
      if (!candidateEntries.has(key)) return false;
      const value = candidateEntries.get(key);
      return value === null || (typeof value === 'string' && value.trim() === '');
    })
    .map((key) => `blank:${key}`);
  const type = [...referenceNodes.keys()]
    .filter(
      (key) =>
        candidateNodes.has(key) &&
        valueType(referenceNodes.get(key)) !== valueType(candidateNodes.get(key)),
    )
    .map(
      (key) =>
        `type:${key}:${valueType(referenceNodes.get(key))}!=${valueType(candidateNodes.get(key))}`,
    );

  return [...missing, ...extra, ...blank, ...type];
};

const readTree = (localeRoot, locale, namespace) => {
  const filePath = path.join(localeRoot, locale, `${namespace}.json`);
  if (!fs.existsSync(filePath)) return null;
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
};

export const validateResources = (localeRoot) => {
  const findings = [];

  NAMESPACES.forEach((namespace) => {
    const reference = readTree(localeRoot, DEFAULT_LOCALE, namespace);
    SUPPORTED_LOCALES.forEach((locale) => {
      const candidate = readTree(localeRoot, locale, namespace);
      if (candidate === null) {
        findings.push(`${locale}/${namespace}: missing:file`);
        return;
      }
      if (reference === null) return;
      validateLocaleTree(reference, candidate).forEach((issue) => {
        findings.push(`${locale}/${namespace}: ${issue}`);
      });
    });
  });

  return {
    findings,
    localeCount: SUPPORTED_LOCALES.length,
    namespaceCount: NAMESPACES.length,
  };
};

const runCli = () => {
  const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
  const localeRoot = path.resolve(scriptDirectory, '../src/i18n/locales');
  const { findings, localeCount, namespaceCount } = validateResources(localeRoot);

  if (findings.length > 0) {
    process.stderr.write(`${findings.join('\n')}\n`);
    process.exitCode = 1;
    return;
  }

  process.stdout.write(
    `i18n parity check passed: ${localeCount} locales, ${namespaceCount} namespaces\n`,
  );
};

const isDirectRun =
  process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isDirectRun) runCli();
