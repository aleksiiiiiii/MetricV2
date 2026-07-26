import { QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';

import { Toaster } from '@/components/ui';
import { AuthProvider } from '@/app/AuthProvider';
import { App } from '@/App';
import { createQueryClient } from '@/lib/query';

// Ordre volontaire : les polices d'abord, puis les tokens, puis le socle qui les
// consomme. Les modules de composants s'importent ensuite, au fil des écrans.
import '@/styles/fonts.css';
import '@/styles/tokens.css';
import '@/styles/base.css';

const root = document.getElementById('root');
if (!root) {
  throw new Error("Élément #root introuvable : index.html n'a pas été chargé.");
}

// `Toaster` enveloppe `AuthProvider` : c'est lui qui annonce une session expirée.
createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={createQueryClient()}>
      <BrowserRouter>
        <Toaster>
          <AuthProvider>
            <App />
          </AuthProvider>
        </Toaster>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
