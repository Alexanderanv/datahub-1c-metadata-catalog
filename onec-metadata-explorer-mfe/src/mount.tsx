import React from 'react';
import { createRoot, Root } from 'react-dom/client';
import { App } from './App';

export function mount(container: HTMLElement, _options: Record<string, unknown> = {}): () => void {
  const root: Root = createRoot(container);
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );

  return () => {
    root.unmount();
  };
}

export default mount;
