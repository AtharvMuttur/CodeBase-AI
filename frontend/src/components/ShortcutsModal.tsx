import { Modal } from "./Modal";

interface Props {
  open: boolean;
  onClose: () => void;
}

interface Shortcut {
  keys: string;
  description: string;
}

const SHORTCUTS: Shortcut[] = [
  { keys: "/", description: "Focus the sidebar search" },
  { keys: "⌘ K / Ctrl K", description: "Focus the chat composer" },
  { keys: "⌘ Enter / Ctrl Enter", description: "Send the current question" },
  { keys: "Esc", description: "Clear the composer or close dialogs" },
  { keys: "Shift Enter", description: "New line in the composer" },
  { keys: "?", description: "Open this shortcuts dialog" },
];

export function ShortcutsModal({ open, onClose }: Props) {
  return (
    <Modal open={open} onClose={onClose} title="Keyboard shortcuts">
      <div className="shortcut-grid">
        {SHORTCUTS.map((s) => (
          <div className="shortcut-row" key={s.keys}>
            <kbd className="shortcut-keys">{s.keys}</kbd>
            <span className="shortcut-desc">{s.description}</span>
          </div>
        ))}
      </div>
    </Modal>
  );
}
