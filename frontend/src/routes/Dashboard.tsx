import { useQuery } from '@tanstack/react-query';

import { Badge, Card, Empty, Eyebrow, Rule } from '@/components/ui';
import { api } from '@/lib/api';
import { keys } from '@/lib/query';
import { longDate, time } from '@/lib/format';

/**
 * Tableau de bord — état d'attente du lot L03.
 *
 * Le vrai écran est construit au lot L08, quand `AGG-01` retournera tous les indicateurs
 * de synthèse en une requête. Il n'affiche donc aucune donnée métier inventée : montrer
 * de faux chiffres dans une application de mesure serait la pire des démonstrations.
 */
export function Dashboard() {
  const { data: health } = useQuery({
    queryKey: keys.health(),
    queryFn: ({ signal }) => api.health(signal),
  });

  return (
    <div className="wrap">
      <Eyebrow>{longDate(new Date())}</Eyebrow>
      <h1 style={{ marginTop: 10 }}>Tableau de bord</h1>
      <p className="lede" style={{ marginTop: 14 }}>
        Le journal instrumenté d'une vie. Chaque jour laisse une trace : une course, un sommeil, une
        heure de code. Metric relève, aligne, et rend la courbe lisible.
      </p>

      <Rule>État du socle</Rule>

      <div className="grid g2">
        <Card>
          <div className="spread">
            <div>
              <h3>Service</h3>
              <p className="eyebrow" style={{ marginTop: 4 }}>
                {health ? `version ${health.version}` : 'interrogation…'}
              </p>
            </div>
            {health && <Badge tone="effort">en ligne</Badge>}
          </div>

          {health && (
            <div className="row" style={{ marginTop: 16 }}>
              <Badge tone={health.storage_configured ? 'effort' : 'load'}>
                {health.storage_configured ? 'Nextcloud configuré' : 'Nextcloud absent'}
              </Badge>
              <Badge tone={health.ai_enabled ? 'effort' : 'load'}>
                {health.ai_enabled ? 'IA disponible' : 'saisie manuelle'}
              </Badge>
              <Badge tone="signal" mono>
                {time(health.time)}
              </Badge>
            </div>
          )}
        </Card>

        <Empty title="Aucun relevé aujourd'hui">
          Deux chiffres suffisent pour que la journée compte.
          <br />
          Trente secondes, et la série tient.
        </Empty>
      </div>

      <Rule>Prochaine étape</Rule>
      <p className="lede">
        Les écrans de saisie arrivent avec les domaines : le corps au lot L04, l'activité au L05,
        l'hydratation et les suppléments au L06. La grille d'assiduité au L11.
      </p>
    </div>
  );
}
