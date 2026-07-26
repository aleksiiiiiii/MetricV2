import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';

import { App } from '@/App';

// Ordre volontaire : les polices d'abord, puis les tokens, puis le socle qui les
// consomme. Les modules de composants s'importent ensuite, au fil des écrans.
import '@/styles/fonts.css';
import '@/styles/tokens.css';
import '@/styles/base.css';

const root = document.getElementById('root');
if (!root) {
  throw new Error("Élément #root introuvable : index.html n'a pas été chargé.");
}

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
