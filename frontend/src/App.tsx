import { Route, Routes } from 'react-router';

import { RequireAuth } from '@/app/RequireAuth';
import { Shell } from '@/app/Shell';
import { Activity } from '@/routes/Activity';
import { Body } from '@/routes/Body';
import { Dashboard } from '@/routes/Dashboard';
import { KitchenSink } from '@/routes/KitchenSink';
import { Login } from '@/routes/Login';
import { Nutrition } from '@/routes/Nutrition';
import { Routine } from '@/routes/Routine';
import { Settings } from '@/routes/Settings';
import { NotFound } from '@/routes/NotFound';

/**
 * Table de routage.
 *
 * La connexion est hors de la coquille : elle n'a ni navigation ni déconnexion à
 * afficher. Tout le reste vit derrière `RequireAuth`.
 */
export function App() {
  return (
    <Routes>
      <Route path="/connexion" element={<Login />} />

      {/* La référence de charte est publique : elle ne contient aucune donnée
          utilisateur, et pouvoir l'ouvrir sans session la rend consultable depuis
          n'importe quel appareil — et vérifiable par une capture automatisée. */}
      <Route path="/_kitchen-sink" element={<KitchenSink />} />

      <Route
        element={
          <RequireAuth>
            <Shell />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Dashboard />} />
        <Route path="/corps" element={<Body />} />
        <Route path="/activite" element={<Activity />} />
        <Route path="/routine" element={<Routine />} />
        <Route path="/nutrition" element={<Nutrition />} />
        <Route path="/reglages" element={<Settings />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
