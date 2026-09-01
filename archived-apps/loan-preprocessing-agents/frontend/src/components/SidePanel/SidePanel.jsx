import React, { useEffect, useRef } from "react";
import "./SidePanel.css";

const SidePanel = ({ isOpen, onClose, children }) => {
  const panelRef = useRef(null);
  const closeButtonRef = useRef(null);
  const previousFocusRef = useRef(null);

  // Close on outside click
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (panelRef.current && !panelRef.current.contains(event.target)) {
        onClose();
      }
    };
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen, onClose]);

  // Keep keyboard focus inside the modal panel and restore it on close.
  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    previousFocusRef.current = document.activeElement;
    closeButtonRef.current?.focus();

    const handleKeyboard = (event) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) {
        return;
      }

      const focusableElements = Array.from(panelRef.current.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      ));
      if (!focusableElements.length) {
        event.preventDefault();
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      } else if (!panelRef.current.contains(document.activeElement)) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener("keydown", handleKeyboard);
    return () => {
      document.removeEventListener("keydown", handleKeyboard);
      previousFocusRef.current?.focus();
    };
  }, [isOpen, onClose]);

  return (
    <div className={`sidepanel-overlay ${isOpen ? "open" : ""}`}>
      <div
        ref={panelRef}
        className={`sidepanel ${isOpen ? "open" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-hidden={!isOpen}
        aria-label="Application processing details"
      >
        <button
          ref={closeButtonRef}
          className="sidepanel-close"
          onClick={onClose}
          aria-label="Close application details"
        >
          ✕
        </button>
        <div className="sidepanel-content">{children}</div>
      </div>
    </div>
  );
};

export default SidePanel;
