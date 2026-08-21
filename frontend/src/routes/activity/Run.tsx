/**
 * La page spécialisée Course — `/activite/course` (`ACT-19`).
 *
 * Une course entrait entière dans `runs.csv` et en ressortait plate : huit champs, aucun
 * palier, aucune comparaison entre le début et la fin. Cette page est ce que les paliers
 * permettent enfin de dire.
 *
 * **Deux adresses pour un seul écran.** `/activite/course` ouvre la dernière course, et
 * `/activite/course/:id` en ouvre une précise depuis l'historique. Le plan ne nommait que
 * la première, mais s'y tenir seule aurait rendu les paliers de toutes les courses
 * antérieures définitivement invisibles — une donnée écrite que rien n'affiche jamais.
 *
 * **Aucun calcul métier ici.** Dérive, moyennes par moitié, extrema, part servie des
 * barres, bornes de l'axe : tout arrive calculé. C'est l'invariant que le tableau de bord
 * vient de retrouver, et le seul `Math` de ce fichier porte sur des secondes d'affichage.
 *
 * ## Ce que le graphique montre, et ce qu'il tait
 *
 * La courbe d'allure ne trace **que les paliers pleins**. L'allure d'un reliquat de 44
 * secondes est une extrapolation de l'application ; la poser sur la même courbe que huit
 * mesures en ferait un point de mesure de plus, ce qu'elle n'est pas. Le tableau, lui, la
 * montre — grisée, et marquée.
 *
 * Les barres de cadence, à l'inverse, comptent **tous** les paliers : 163 pas par minute
 * sur 44 secondes est une mesure aussi valable que sur cinq minutes. C'est la seule
 * asymétrie de l'écran, et elle vient de la donnée, pas d'une préférence.
 */

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router';

import {
  Badge,
  Bars,
  Card,
  Chart,
  Empty,
  LinkButton,
  PageHead,
  Rule,
  Stat,
  Table,
} from '@/components/ui';
import type { Column } from '@/components/ui';
import { activityApi, type RunSplit, type RunSplits } from '@/features/activity/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { duration, integer, longDate, num, pace, plural } from '@/lib/format';
import { keys } from '@/lib/query';

import styles from '../Activity.module.css';

/** En deçà, « la course est régulière » est plus vrai que le signe de la dérive. */
const STEADY_S_PER_KM = 1;

/**
 * Ce que la dérive veut dire, en toutes lettres.
 *
 * Le signe seul se lit à l'envers : `-4,2` est une **accélération**, parce qu'une allure
 * qui baisse est une course qui va plus vite. Montrer le nombre sans la phrase serait
 * offrir au lecteur la meilleure occasion de conclure l'inverse de la vérité.
 */
function drift(seconds: number): { label: string; detail: string } {
  if (Math.abs(seconds) < STEADY_S_PER_KM) {
    return { label: 'Régulière', detail: 'moins d’une seconde par kilomètre d’écart' };
  }
  // Le détail ne **répète pas** le chiffre : la tuile l'affiche déjà juste au-dessus, et
  // les deux collés se lisaient « 4,2 s/km · 4,2 s/km plus vite… ». Il dit le sens,
  // qui est ce que le nombre seul ne dit pas.
  return seconds < 0
    ? { label: 'Accélération', detail: 'gagnées sur la seconde moitié de la course' }
    : { label: 'Ralentissement', detail: 'perdues sur la seconde moitié de la course' };
}

/**
 * Les colonnes du tableau des paliers — trois, et **pas** de cadence.
 *
 * Elle y était, et elle en est sortie sur constat : à 360 px la quatrième colonne se
 * coupait au premier chiffre — « 1 » pour 166. Le tableau défilait bien dans son propre
 * conteneur, donc rien n'était perdu ni cassé, mais on lisait un nombre tronqué avant de
 * penser à le tirer.
 *
 * Ce qui a tranché n'est pas la largeur : la cadence de chaque palier est **déjà** au
 * complet dans les barres juste au-dessus, avec son chiffre. La colonne ne répétait donc
 * qu'une information entière, et la retirer ne coûte rien du tout.
 */
function columns(data: RunSplits): Column<RunSplit>[] {
  return [
    {
      key: 'index',
      header: 'Km',
      render: (split) =>
        split.partial ? (
          // Le reliquat porte ce qu'il est, plutôt qu'un numéro qui le ferait passer
          // pour un neuvième kilomètre.
          <Badge tone="load">reliquat</Badge>
        ) : (
          <span className="num">{split.index}</span>
        ),
    },
    {
      key: 'time',
      header: 'Temps',
      numeric: true,
      render: (split) => duration(split.duration_s / 60),
    },
    {
      key: 'pace',
      header: 'Allure',
      numeric: true,
      render: (split) =>
        split.pace_min_km == null ? (
          <span className={styles.empty}>—</span>
        ) : (
          // Grisée sur un partiel : l'application l'a extrapolée d'une fraction de
          // kilomètre, et elle ne se compare pas aux huit autres.
          //
          // `paceCell` tient la valeur et sa marque **sur une seule ligne** : à 390 px, le
          // triangle passait à la ligne suivante et les deux rangées marquées étaient plus
          // hautes que les sept autres — un tableau qui respire irrégulièrement pour la
          // seule raison qu'on y a signalé quelque chose.
          <span className={cx(styles.paceCell, split.partial && styles.extrapolated)}>
            {pace(split.pace_min_km)}
            {split.index === data.fastest_index && <span className={styles.mark}>▲</span>}
            {split.index === data.slowest_index && <span className={styles.mark}>▼</span>}
          </span>
        ),
    },
  ];
}

export function Run() {
  // `id` absent = « la dernière ». Le seul calcul de l'écran est de choisir quelle page
  // demander, ce que l'invariant de date autorise explicitement.
  const { id } = useParams<{ id: string }>();
  const chosen = id === undefined ? null : Number(id);

  const { data, isPending, error } = useQuery({
    queryKey: chosen === null ? keys.activity.latestRun() : keys.activity.runSplits(chosen),
    queryFn: () => (chosen === null ? activityApi.latestRun() : activityApi.runSplits(chosen)),
  });

  const run = data?.run ?? null;
  const detail = data?.splits;
  const full = detail?.splits.filter((split) => !split.partial) ?? [];
  const cadenced = detail?.splits.filter((split) => split.cadence_spm != null) ?? [];

  return (
    <div className={cx('wrap', styles.screen)}>
      {/* L'en-tête est là **avant** la donnée : un écran qui n'affiche qu'un
          « chargement… » ne dit pas où l'on vient d'arriver. */}
      <PageHead
        eyebrow="Domaine Activité"
        title="Course"
        actions={
          <LinkButton variant="quiet" to="/activite">
            Retour à l’activité
          </LinkButton>
        }
      >
        {run ? longDate(run.date) : 'Le détail d’une sortie, palier par palier.'}
      </PageHead>

      {error !== null ? (
        <Card>
          <Empty title="Course indisponible">
            {error instanceof ApiError ? error.message : 'Le serveur n’a pas répondu.'}
          </Empty>
        </Card>
      ) : isPending ? (
        <Card>
          <p className={styles.empty}>chargement…</p>
        </Card>
      ) : run === null || detail === undefined ? (
        <Card>
          {/* Aucune valeur inventée : un tiret et ce que coûte le prochain geste. */}
          <Empty title="Aucune course enregistrée">
            Importe une capture Apple depuis l’activité — le résumé et les paliers en deux images —
            ou saisis la course à la main.
          </Empty>
        </Card>
      ) : (
        <>
          <div className="grid tiles">
            <Card>
              <Stat compact label="Distance" value={num(run.distance_km, 2)} unit="km" />
            </Card>
            <Card>
              <Stat compact label="Durée" value={duration(run.duration_min)} />
            </Card>
            <Card>
              <Stat
                compact
                label="Allure moyenne"
                value={run.pace_min_km == null ? '—' : pace(run.pace_min_km)}
                unit={run.pace_min_km == null ? undefined : '/km'}
              />
            </Card>
            <Card>
              <Stat
                compact
                label="Cadence moyenne"
                value={run.cadence_spm == null ? '—' : integer(run.cadence_spm)}
                unit={run.cadence_spm == null ? undefined : 'spm'}
                detail={run.cadence_spm == null ? 'non relevée' : undefined}
              />
            </Card>
          </div>

          {detail.splits.length === 0 ? (
            <Card>
              <Empty title="Pas de paliers pour cette course">
                Elle a été saisie au clavier. Les paliers viennent d’un import de captures : le
                résumé, puis la liste « Splits ».
              </Empty>
            </Card>
          ) : (
            <>
              <Rule>Allure par palier</Rule>

              {detail.drift_s_per_km != null && (
                <Card>
                  <Stat
                    label={drift(detail.drift_s_per_km).label}
                    value={`${num(Math.abs(detail.drift_s_per_km), 1)} s/km`}
                    detail={drift(detail.drift_s_per_km).detail}
                    direction={detail.drift_s_per_km < 0 ? 'up' : 'down'}
                  />
                  <p className={styles.note}>
                    Moyenne de la seconde moitié des paliers pleins moins celle de la première
                    {detail.first_half_pace_min_km != null &&
                      detail.second_half_pace_min_km != null &&
                      ` — ${pace(detail.first_half_pace_min_km)} puis ${pace(detail.second_half_pace_min_km)} au kilomètre`}
                    . Le reliquat n’y entre pas.
                  </p>
                </Card>
              )}

              <Card>
                <h3>Allure, kilomètre par kilomètre</h3>
                <p className={styles.note}>
                  L’axe est inversé : plus le point est haut, plus le kilomètre a été rapide.
                </p>
                {full.length >= 2 ? (
                  <Chart
                    labels={full.map((split) => `km ${String(split.index)}`)}
                    primary={{
                      label: 'Allure',
                      unit: 'min/km',
                      values: full.map((split) => split.pace_min_km ?? 0),
                      tone: 'signal',
                      format: (value) => pace(value),
                      // Les bornes arrivent **déjà retournées** par le serveur, le plus
                      // lent d'abord : l'écran ne décide pas du sens d'un axe.
                      ...(detail.pace_domain_min_km ? { domain: detail.pace_domain_min_km } : {}),
                    }}
                    note={
                      detail.partial_count > 0
                        ? `Le reliquat de fin n’est pas tracé : son allure est extrapolée.`
                        : undefined
                    }
                  />
                ) : (
                  <p className={cx(styles.empty, styles.emptyInset)}>
                    il faut deux kilomètres pleins pour tracer une courbe
                  </p>
                )}
              </Card>

              {/* La carte entière disparaît quand aucun palier ne porte de cadence — une
                  capture dont la liste n'a que deux colonnes. Un titre suivi de rien
                  laisserait croire à une section qui n'a pas fini de charger. */}
              {cadenced.length > 0 && (
                <Card>
                  <h3>Cadence par palier</h3>
                  {/* La phrase ne cite **aucun chiffre** de cette course-ci. Elle en citait
                      un — « seize pas par minute d’écart », l’amplitude de la sortie de
                      référence — qui aurait été faux sur toutes les autres. Un nombre écrit
                      en dur dans une phrase est une valeur inventée comme une autre. */}
                  <p className={styles.note}>
                    Les barres partent du maximum de la course et non de zéro. Sur une foulée qui ne
                    varie que de quelques pas par minute, une échelle plus généreuse la ferait
                    passer pour une foulée en dents de scie.
                  </p>
                  <Bars
                    rows={cadenced.map((split) => ({
                      label: split.partial ? 'reliquat' : `km ${String(split.index)}`,
                      // La part vient du serveur : aucun `Math.max` sur des mesures.
                      ratio: split.cadence_ratio ?? 0,
                      value: `${integer(split.cadence_spm ?? 0)} spm`,
                      tone: split.partial ? 'load' : 'effort',
                    }))}
                  />
                </Card>
              )}

              <Rule>
                {detail.full_count} {plural(detail.full_count, 'palier')}
                {detail.partial_count > 0 && ' et un reliquat'}
              </Rule>
              <Card>
                <Table
                  columns={columns(detail)}
                  rows={detail.splits}
                  rowKey={(split) => String(split.index)}
                  caption="Paliers de la course, temps et allure"
                />
              </Card>
            </>
          )}

          {(run.total_calories != null || run.elevation_m != null) && (
            <>
              <Rule>Le reste de la séance</Rule>
              <div className="grid tiles">
                {run.total_calories != null && (
                  <Card>
                    {/* Nommées. Jamais un chiffre seul appelé « calories » : une capture
                        Apple en affiche deux, et elles ne veulent pas dire la même chose. */}
                    <Stat
                      compact
                      label="Calories totales"
                      value={integer(run.total_calories)}
                      unit="kcal"
                      detail="métabolisme de base compris"
                    />
                  </Card>
                )}
                {run.elevation_m != null && (
                  <Card>
                    <Stat
                      compact
                      label="Dénivelé positif"
                      value={integer(run.elevation_m)}
                      unit="m"
                    />
                  </Card>
                )}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
