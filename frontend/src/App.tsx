import { Route, Routes } from 'react-router';

import { RequireAuth } from '@/app/RequireAuth';
import { Shell } from '@/app/Shell';
import { Activity } from '@/routes/Activity';
import { Circuits } from '@/routes/activity/Circuits';
import { Compose } from '@/routes/activity/Compose';
import { Loads } from '@/routes/activity/Loads';
import { Run } from '@/routes/activity/Run';
import { Runs } from '@/routes/activity/Runs';
import { Assiduity } from '@/routes/Assiduity';
import { Assistant } from '@/routes/Assistant';
import { Body } from '@/routes/Body';
import { Dashboard } from '@/routes/Dashboard';
import { Goals } from '@/routes/Goals';
import { KitchenSink } from '@/routes/KitchenSink';
import { Login } from '@/routes/Login';
import { Nutrition } from '@/routes/Nutrition';
import { Planning } from '@/routes/Planning';
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
        {/* Les sous-pages d'Activité, et non des replis sans adresse. Elles n'entrent
            ni dans `NAV` ni dans `MORE` : on y arrive par un bouton de leur page mère,
            comme on ouvre un dossier depuis celui qui le contient. Ce qu'elles gagnent à
            être des routes est le bouton système « précédent », qui ramène à l'écran
            d'où l'on vient au lieu de quitter l'application.

            `/activite/catalogue` et `/activite/statistiques` ont disparu avec
            `exercise_log.csv` : le catalogue était celui de Metric, que celui de Cadence
            remplace, et les statistiques dérivaient toutes du tonnage. */}
        <Route path="/activite/seances" element={<Circuits />} />
        <Route path="/activite/creer" element={<Compose />} />
        <Route path="/activite/charges" element={<Loads />} />
        {/* Deux adresses, un seul écran. Sans paramètre, c'est la dernière course —
            l'adresse que le plan nomme. Avec, celle qu'on ouvre depuis l'historique :
            s'en tenir à la première aurait rendu les paliers de toutes les courses
            précédentes invisibles, c'est-à-dire écrits pour rien. */}
        <Route path="/activite/courses" element={<Runs />} />
        <Route path="/activite/course" element={<Run />} />
        <Route path="/activite/course/:id" element={<Run />} />
        <Route path="/planning" element={<Planning />} />
        <Route path="/objectif" element={<Goals />} />
        {/* Sans entrée de navigation : la barre demandait déjà 806 px pour 695
            disponibles. On y arrive depuis le tableau de bord et l'écran Objectif. */}
        <Route path="/assistant" element={<Assistant />} />
        <Route path="/assiduite" element={<Assiduity />} />
        <Route path="/routine" element={<Routine />} />
        <Route path="/nutrition" element={<Nutrition />} />
        <Route path="/reglages" element={<Settings />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
