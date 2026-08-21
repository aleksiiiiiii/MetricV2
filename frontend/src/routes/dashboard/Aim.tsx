/**
 * « Où je vais » — la section qui manquait.
 *
 * Le reproche d'où part ce lot tient en une phrase : « **on ne sait pas où on va** ».
 * C'était exact au pied de la lettre — l'objectif du projet, celui de `goals.csv`, avec
 * son ratio, son libellé chiffré et sa fenêtre d'observation, n'apparaissait sur **aucun**
 * écran d'accueil. Le seul « objectif » qu'on y lisait était l'écart à la cible de poids,
 * tout en bas de la page et sous condition.
 *
 * ## Trois blocs, un seul affiché — et le choix n'est pas un calcul
 *
 * L'objectif en cours s'il y en a un ; à défaut la cible de poids si elle est réglée ; à
 * défaut l'état vide, qui dit ce que coûte le prochain geste. Choisir lequel des trois
 * blocs **déjà servis** dessiner est de la présentation, pas une dérivation : aucun
 * chiffre n'est produit ici, et les trois arrivent calculés du serveur.
 *
 * ## Ce qui n'est pas dessiné
 *
 * **Pas d'anneau quand l'avancement est indéterminé.** `progress.ratio` vaut `null` quand
 * rien n'avait été relevé à l'adoption, et un anneau dessine un pourcentage — c'est ce
 * qu'il sait faire. C'est précisément par là que l'invariant s'est cassé au L14 : quatre
 * décisions correctes, et « 0 % » au centre d'une donnée absente. `Ring` porte le cas dans
 * son type depuis ; on ne le lui reprend pas.
 */

import { Card, Empty, LinkButton, Ring, Rule, Stat } from '@/components/ui';
import type { DashboardView } from '@/features/aggregates/api';
import type { ActiveGoal } from '@/features/goals/api';
import { kg, num, plural, shortDate } from '@/lib/format';

import styles from '../Dashboard.module.css';

/** Jours restants, en clair. Le serveur donne le nombre ; le français est ici. */
function deadlineLine(days: number, deadline: string): string {
  const when = shortDate(`${deadline}T12:00:00`);
  if (days < 0)
    return `échéance dépassée depuis ${String(-days)} ${plural(-days, 'jour')} — ${when}`;
  if (days === 0) return `dernier jour — ${when}`;
  return `${String(days)} ${plural(days, 'jour')} ${plural(days, 'restant')} — ${when}`;
}

function CurrentGoal({ active }: { active: ActiveGoal }) {
  const { goal, progress } = active;

  return (
    <Card>
      <div className="spread">
        <div>
          <p className="eyebrow">Objectif en cours</p>
          <h3>{goal.title}</h3>
        </div>
        <LinkButton variant="ghost" to="/objectif">
          Détail
        </LinkButton>
      </div>

      <div className={styles.aim}>
        {progress.ratio !== null && (
          <Ring
            ratio={progress.ratio}
            label={progress.label}
            tone={progress.ratio >= 1 ? 'effort' : 'signal'}
          />
        )}

        <div className={styles.aimFigures}>
          {/* Tous ces textes arrivent **rédigés** par le serveur : le libellé chiffré et
              la fenêtre d'observation. Les reformuler ici en donnerait deux versions. */}
          <span className={styles.aimSummary}>{progress.summary}</span>
          <span className={styles.aimNote}>{progress.basis}</span>
          <span className={styles.aimNote}>{deadlineLine(active.days_left, goal.deadline)}</span>
        </div>
      </div>
    </Card>
  );
}

export function Aim({ data }: { data: DashboardView }) {
  const { goal, weight } = data;

  return (
    <>
      <Rule>Où je vais</Rule>

      {goal !== null ? (
        <CurrentGoal active={goal} />
      ) : weight.to_target_kg !== null ? (
        <Card>
          <Stat
            label={`Cible de poids ${kg(weight.target_kg)}`}
            value={num(Math.abs(weight.to_target_kg), 1)}
            unit="kg"
            detail={weight.to_target_kg > 0 ? 'restants pour atteindre la cible' : 'sous la cible'}
            direction={weight.to_target_kg > 0 ? 'up' : 'down'}
          />
          {/* La cible de poids est un **réglage**, pas un objectif daté. Le dire évite de
              laisser croire que l'écran répond déjà à « où je vais ». */}
          <p className={styles.aimNote}>
            C’est un réglage, pas un objectif daté. Un objectif se fixe sur quatre à huit semaines
            et se juge sur une fenêtre.
          </p>
          <div className="row">
            <LinkButton variant="ghost" to="/objectif">
              Fixer un objectif
            </LinkButton>
          </div>
        </Card>
      ) : (
        <Empty
          title="Aucun objectif en cours"
          action={<LinkButton to="/objectif">Fixer un objectif</LinkButton>}
        >
          Un seul objectif, chiffré, daté de quatre à huit semaines. C’est lui qui donne un sens aux
          chiffres du dessus.
        </Empty>
      )}
    </>
  );
}
