import { QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';

import { Toaster } from '@/components/ui';
import { AuthProvider } from '@/app/AuthProvider';
import { ThemeProvider } from '@/app/ThemeProvider';
import { App } from '@/App';
import { registerServiceWorker } from '@/lib/pwa';
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
// `ThemeProvider` les enveloppe tous : le thème vaut aussi pour l'écran de connexion et
// pour l'attente de session, qui sont rendus hors de la coquille.
createRoot(root).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={createQueryClient()}>
        <BrowserRouter>
          <Toaster>
            <AuthProvider>
              <App />
            </AuthProvider>
          </Toaster>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
);

// Après le rendu, et sans l'attendre : le worker n'apporte que l'ouverture hors ligne de
// la coquille et la réception des rappels. Rien de ce que l'écran affiche n'en dépend, et
// un enregistrement qui échoue ne doit pas retarder d'une milliseconde la première
// peinture.
void registerServiceWorker();
