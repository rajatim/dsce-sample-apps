import React, { useState } from 'react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import SidePanel from './SidePanel';

const sidePanelStyles = readFileSync(resolve('src/components/SidePanel/SidePanel.css'), 'utf8');

const SidePanelHarness = () => {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setIsOpen(true)}>Open details</button>
      <SidePanel isOpen={isOpen} onClose={() => setIsOpen(false)}>
        <button type="button">Panel action</button>
        <a href="#next">Last panel link</a>
      </SidePanel>
    </>
  );
};

describe('SidePanel keyboard focus', () => {
  it('moves focus into the panel, traps Tab, and restores the trigger after Escape', () => {
    render(<SidePanelHarness />);
    const trigger = screen.getByRole('button', { name: 'Open details' });

    trigger.focus();
    fireEvent.click(trigger);

    const closeButton = screen.getByRole('button', { name: 'Close application details' });
    const lastLink = screen.getByRole('link', { name: 'Last panel link' });
    expect(closeButton).toHaveFocus();

    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(lastLink).toHaveFocus();

    fireEvent.keyDown(document, { key: 'Tab' });
    expect(closeButton).toHaveFocus();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(trigger).toHaveFocus();
  });
});

describe('SidePanel stacking', () => {
  afterEach(() => {
    document.querySelector('[data-sidepanel-test-styles]')?.remove();
  });

  it('renders the open panel above the fixed Carbon header', () => {
    const styleElement = document.createElement('style');
    styleElement.dataset.sidepanelTestStyles = 'true';
    styleElement.textContent = sidePanelStyles;
    document.head.appendChild(styleElement);

    render(
      <>
        <header data-testid="carbon-header" style={{ position: 'fixed', zIndex: 8000 }} />
        <SidePanel isOpen onClose={() => {}}>
          Application details
        </SidePanel>
      </>
    );

    const headerZIndex = Number(window.getComputedStyle(screen.getByTestId('carbon-header')).zIndex);
    const overlayZIndex = Number(window.getComputedStyle(document.querySelector('.sidepanel-overlay')).zIndex);

    expect(overlayZIndex).toBeGreaterThan(headerZIndex);
  });
});
