import React, { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SidePanel from './SidePanel';

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
