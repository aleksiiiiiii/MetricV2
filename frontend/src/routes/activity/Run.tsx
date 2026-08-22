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
 *
 * ## Les deux dérives ne se lisent pas dans le même sens
 *
 * L'allure baisse quand on accélère ; la cadence monte. Les afficher côte à côte en
 * nombres signés donnerait deux flèches opposées pour un même constat — la page nomme
 * donc chacune en toutes lettres, et ne montre le signe nulle part seul.
 *
 * ## Ce que le contexte ajoute, et la réserve qu'il porte
 *
 * Une course seule ne se compare à rien. La dernière section la replace parmi les autres,
 * mais un rang d'allure entre un 8 km et un 3 km est bancal : il s'affiche donc toujours
 * **avec le nombre de courses comparées**, jamais comme un classement absolu.
 */

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router';

import {
  Badge,
  Card,
  Chart,
  Deviation,
  Empty,
  LinkButton,
  PageHead,
  Rule,
  Stat,
  Table,
} from '@/components/ui';
import type { Column } from '@/components/ui';
import {
  activityApi,
  type RunContext,
  type RunSplit,
  type RunSplits,
} from '@/features/activity/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { dayMonth, duration, integer, longDate, num, pace, plural } from '@/lib/format';
import { keys } from '@/lib/query';

import styles from '../Activity.module.css';

/** En deçà, « la course est régulière » est plus vrai que le signe de la dérive. */
const STEADY_S_PER_KM = 1;

/** Même idée sur la cadence : en deçà d'un pas par minute, la foulée n'a pas bougé. */
const STEADY_SPM = 1;

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
 * Ce que la dérive de cadence veut dire, en toutes lettres.
 *
 * **Son signe est l'inverse de celui de la dérive d'allure.** Positif, la foulée s'est
 * accélérée — ce qui est la même bonne nouvelle qu'une dérive d'allure négative. Deux
 * grandeurs dont les signes se contredisent sur le même constat sont exactement le genre
 * de chose qu'un écran doit écrire plutôt que laisser déduire.
 */
function cadenceDrift(steps: number): { label: string; detail: string } {
  if (Math.abs(steps) < STEADY_SPM) {
    return { label: 'Foulée stable', detail: 'la fréquence n’a pas bougé d’un pas' };
  }
  return steps > 0
    ? { label: 'Foulée plus fréquente', detail: 'pas par minute gagnés sur la seconde moitié' }
    : { label: 'Foulée moins fréquente', detail: 'pas par minute perdus sur la seconde moitié' };
}

/**
 * La régularité, en un mot.
 *
 * L'écart-type est en secondes par kilomètre, et les bornes se lisent dans cette unité.
 * Elles viennent de ce que la course produit réellement : une allure tenue au métronome
 * tourne autour de trois secondes, une sortie tranquille sous dix, un parcours à feux
 * rouges et à côtes dépasse la vingtaine, et une séance de fractionné explose l'échelle.
 *
 * Elles sont grossières **à dessein** — un adjectif qui changerait pour une demi-seconde
 * donnerait à ce chiffre une précision qu'il n'a pas. Le premier seuil a été relevé de 5
 * à 8 après coup : la course de référence tient dans 5,8 s/km d'écart-type sur huit
 * kilomètres, ce qu'aucun coureur n'appellerait autrement que très régulier.
 */
function steadiness(sd: number): string {
  if (sd < 8) return 'très régulière';
  if (sd < 18) return 'régulière';
  if (sd < 35) return 'en dents de scie';
  return 'très irrégulière';
}

/**
 * La course replacée parmi les autres.
 *
 * **Sous deux courses, la section n'existe pas.** Une première sortie ne se compare à
 * rien, et le « 1ᵉʳ sur 1 » qu'on afficherait alors se lirait comme un record — la pire
 * espèce de valeur inventée, celle qui est littéralement exacte.
 *
 * Le rang ne s'affiche **jamais seul** : comparer l'allure d'un 8 km à celle d'un 3 km est
 * bancal, et le taire serait pire que le dire. « 2ᵉ sur 3 » laisse l'utilisateur juger de
 * ce qui est comparable ; « 2ᵉ » déciderait à sa place.
 */
function Context({ context }: { context: RunContext }) {
  if (context.runs_compared < 2) return null;

  const trend = context.recent.filter((mark) => mark.pace_min_km != null);
  // Retrouver le point que le serveur a marqué n'est pas un calcul métier : c'est lire un
  // drapeau posé dans la donnée. Le rang est celui de la courbe telle qu'elle est tracée.
  const marked = trend.findIndex((mark) => mark.current);
  const position = marked === -1 ? null : marked + 1;
  return (
    <>
      <Rule>Parmi tes {context.runs_compared} courses</Rule>

      <div className="grid tiles">
        {context.pace_rank != null && (
          <Card>
            <Stat
              compact
              label="Rang d’allure"
              value={context.pace_rank}
              unit={`sur ${String(context.runs_compared)}`}
              detail={
                context.pace_delta_s_per_km == null
                  ? undefined
                  : context.pace_delta_s_per_km < 0
                    ? `${num(Math.abs(context.pace_delta_s_per_km), 0)} s/km plus vite que ta moyenne`
                    : `${num(context.pace_delta_s_per_km, 0)} s/km plus lent que ta moyenne`
              }
              direction={
                context.pace_delta_s_per_km == null
                  ? undefined
                  : context.pace_delta_s_per_km < 0
                    ? 'up'
                    : 'down'
              }
            />
          </Card>
        )}
        {context.distance_rank != null && (
          <Card>
            <Stat
              compact
              label="Rang de distance"
              value={context.distance_rank}
              unit={`sur ${String(context.runs_compared)}`}
              detail={
                context.distance_delta_km == null
                  ? undefined
                  : `${context.distance_delta_km > 0 ? '+' : ''}${num(context.distance_delta_km, 1)} km sur ta moyenne`
              }
            />
          </Card>
        )}
        {context.best_pace_min_km != null && (
          <Card>
            <Stat
              compact
              label="Allure record"
              value={pace(context.best_pace_min_km)}
              unit="/km"
              detail="toutes courses confondues"
            />
          </Card>
        )}
        {context.longest_distance_km != null && (
          <Card>
            <Stat
              compact
              label="Distance record"
              value={num(context.longest_distance_km, 2)}
              unit="km"
            />
          </Card>
        )}
      </div>

      {trend.length >= 2 && (
        <Card>
          <h3>Allure des dernières sorties</h3>
          <p className={styles.note}>
            L’axe est inversé comme celui des paliers : plus le point est haut, plus la sortie a été
            rapide. Les distances diffèrent d’une course à l’autre — une sortie longue et une sortie
            courte ne se courent pas à la même allure, et la courbe ne le corrige pas.
          </p>
          <Chart
            labels={trend.map((mark) => dayMonth(mark.date))}
            primary={{
              label: 'Allure',
              unit: 'min/km',
              values: trend.map((mark) => mark.pace_min_km ?? 0),
              tone: 'signal',
              format: (value) => pace(value),
              // Les bornes arrivent retournées du serveur, comme celles des paliers.
              // Les chercher ici aurait été un `Math.max` sur une collection de mesures,
              // c'est-à-dire précisément le défaut que la page Activité traîne encore.
              ...(context.pace_domain_min_km ? { domain: context.pace_domain_min_km } : {}),
            }}
            band={{
              label: 'Distance',
              unit: 'km',
              values: trend.map((mark) => mark.distance_km),
              tone: 'load',
              // L'infobulle colle `format` et `unit` : rendre l'unité dans les deux
              // donnait « 8,1 km km ».
              format: (value) => num(value, 1),
            }}
            // Sans cette phrase, la courbe ne dit pas lequel de ses points est la course
            // ouverte. C'est sans conséquence sur la dernière — elle ferme la courbe —,
            // mais `/activite/course/:id` ouvre aussi les anciennes, et le point se
            // retrouve alors au milieu sans rien qui le désigne.
            note={
              position === null
                ? undefined
                : position === trend.length
                  ? 'Cette sortie est le dernier point de la courbe.'
                  : `Cette sortie est le ${String(position)}ᵉ point de la courbe.`
            }
          />
        </Card>
      )}
    </>
  );
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
      key: 'stride',
      header: 'Foulée',
      numeric: true,
      // La foulée et non la cadence : celle-ci est déjà entière dans les barres
      // au-dessus, celle-là n'existe qu'ici et dans sa courbe. Une colonne qui répète
      // une information complète ne paie pas sa largeur sur 390 px.
      render: (split) =>
        split.stride_m == null ? (
          <span className={styles.empty}>—</span>
        ) : (
          <span className={cx(split.partial && styles.extrapolated)}>{num(split.stride_m, 2)}</span>
        ),
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
  // La foulée demande **les deux** mesures : sans cadence, pas de pas comptés. Filtrer
  // sur `stride_m` plutôt que sur la cadence évite une courbe à trous là où le serveur
  // n'a pas pu la calculer.
  const strided = detail?.splits.filter((split) => split.stride_m != null) ?? [];

  return (
    <div className={cx('wrap', styles.screen)}>
      {/* L'en-tête est là **avant** la donnée : un écran qui n'affiche qu'un
          « chargement… » ne dit pas où l'on vient d'arriver. */}
      <PageHead
        eyebrow="Domaine Activité"
        title="Course"
        actions={
          <LinkButton variant="quiet" to="/activite/courses">
            Toutes tes courses
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
                label="Vitesse moyenne"
                value={run.speed_kmh == null ? '—' : num(run.speed_kmh, 1)}
                unit={run.speed_kmh == null ? undefined : 'km/h'}
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
            {detail?.stride_avg_m != null && (
              <Card>
                {/* La foulée croise deux mesures indépendantes — la distance parcourue et
                    les pas comptés. Aucune application du marché ne l'affiche, et elle se
                    déduit pourtant de ce que toutes montrent. */}
                <Stat
                  compact
                  label="Foulée moyenne"
                  value={num(detail.stride_avg_m, 2)}
                  unit="m/pas"
                  detail="distance ÷ pas comptés"
                />
              </Card>
            )}
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
              <Rule>Régularité</Rule>

              {/* Une course de 8 km à 5'02" peut être huit kilomètres identiques ou quatre
                  sprints et quatre marches. La moyenne ne les distingue pas ; ces trois
                  chiffres-là si — et c'est la première chose que la page ajoute à ce que
                  la capture montrait déjà. */}
              <div className="grid tiles">
                {detail.pace_sd_s_per_km != null && (
                  <Card>
                    <Stat
                      compact
                      label="Écart-type"
                      value={num(detail.pace_sd_s_per_km, 1)}
                      unit="s/km"
                      detail={`course ${steadiness(detail.pace_sd_s_per_km)}`}
                    />
                  </Card>
                )}
                {detail.pace_spread_s_per_km != null && (
                  <Card>
                    <Stat
                      compact
                      label="Amplitude"
                      value={num(detail.pace_spread_s_per_km, 0)}
                      unit="s/km"
                      detail="du plus rapide au plus lent"
                    />
                  </Card>
                )}
                {detail.fastest_pace_min_km != null && (
                  <Card>
                    <Stat
                      compact
                      label="Kilomètre le plus rapide"
                      value={pace(detail.fastest_pace_min_km)}
                      unit="/km"
                      detail={
                        detail.fastest_index == null
                          ? undefined
                          : `km ${String(detail.fastest_index)}`
                      }
                    />
                  </Card>
                )}
                {detail.slowest_pace_min_km != null && (
                  <Card>
                    <Stat
                      compact
                      label="Kilomètre le plus lent"
                      value={pace(detail.slowest_pace_min_km)}
                      unit="/km"
                      detail={
                        detail.slowest_index == null
                          ? undefined
                          : `km ${String(detail.slowest_index)}`
                      }
                    />
                  </Card>
                )}
              </div>

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

              {detail.deviation_max_s_per_km != null && (
                <Card>
                  <h3>Écart à la moyenne, kilomètre par kilomètre</h3>
                  <p className={styles.note}>
                    Chaque barre part de l’allure moyenne des paliers pleins
                    {detail.average_pace_min_km != null &&
                      `, ${pace(detail.average_pace_min_km)} au kilomètre`}
                    . À gauche, le kilomètre a été couru plus vite que cette moyenne ; à droite,
                    plus lentement.
                  </p>
                  <Deviation
                    rows={detail.splits.map((split) => ({
                      label: split.partial ? 'reliquat' : `km ${String(split.index)}`,
                      // Signe et longueur viennent du serveur. Une barre qui choisirait
                      // son côté referait ici, sur une collection, le calcul que
                      // l'invariant interdit une fois plutôt que deux.
                      ratio: split.deviation_ratio,
                      value:
                        split.delta_s_per_km == null
                          ? 'extrapolé'
                          : `${split.delta_s_per_km > 0 ? '+' : ''}${num(split.delta_s_per_km, 1)} s`,
                      // Sauge à gauche pour les kilomètres gagnés, argile à droite pour
                      // ceux qui ont coûté : ce sont les deux tons que la charte donne à
                      // « activité » et à « seuil approché ». `Deviation` n'a aucun
                      // défaut là-dessus — seul l'appelant sait de quel côté est la bonne
                      // nouvelle, et sur une allure elle est du côté négatif.
                      tones: ['effort', 'load'] as const,
                      muted: split.partial,
                    }))}
                  />
                </Card>
              )}

              {detail.cadence_drift_spm != null && (
                <>
                  <Rule>Cadence et foulée</Rule>
                  <Card>
                    <Stat
                      label={cadenceDrift(detail.cadence_drift_spm).label}
                      value={`${num(Math.abs(detail.cadence_drift_spm), 1)} spm`}
                      detail={cadenceDrift(detail.cadence_drift_spm).detail}
                      direction={detail.cadence_drift_spm > 0 ? 'up' : 'down'}
                    />
                    {/* Le rappel qui empêche la lecture inverse : les deux dérives de la
                        page portent des signes opposés pour dire la même chose. */}
                    <p className={styles.note}>
                      Le signe se lit à l’envers de celui de l’allure : une cadence qui monte est
                      une foulée plus fréquente, donc — à foulée de même longueur — une course plus
                      rapide.
                    </p>
                  </Card>
                </>
              )}

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
                    Chaque barre est l’écart à la cadence moyenne
                    {detail.cadence_avg_spm != null &&
                      `, ${integer(detail.cadence_avg_spm)} pas par minute`}
                    . Une foulée ne varie que de quelques pas : mesurée depuis zéro, elle donnerait
                    neuf barres pleines et identiques.
                  </p>
                  <Deviation
                    rows={cadenced.map((split) => ({
                      label: split.partial ? 'reliquat' : `km ${String(split.index)}`,
                      // Signe et longueur viennent du serveur, comme pour l'allure.
                      ratio: split.cadence_deviation_ratio,
                      value: `${integer(split.cadence_spm ?? 0)} spm`,
                      // Une cadence **haute** est la foulée fréquente : la bonne nouvelle
                      // est ici du côté positif, à l'inverse de l'allure. C'est la même
                      // inversion de signe que les deux dérives, dite une troisième fois.
                      tones: ['load', 'effort'] as const,
                    }))}
                  />
                </Card>
              )}

              {strided.length >= 2 && (
                <Card>
                  <h3>Longueur de foulée</h3>
                  <p className={styles.note}>
                    Mètres parcourus par pas, palier par palier. Deux kilomètres à la même allure ne
                    se courent pas de la même façon : l’un peut l’être en allongeant la foulée,
                    l’autre en accélérant sa fréquence. La cadence, en pointillé, dit lequel.
                  </p>
                  <Chart
                    labels={strided.map((split) =>
                      split.partial ? 'reliq.' : `km ${String(split.index)}`,
                    )}
                    primary={{
                      label: 'Foulée',
                      unit: 'm/pas',
                      values: strided.map((split) => split.stride_m ?? 0),
                      tone: 'load',
                      // Le nombre seul : la légende écrit « Foulée (m/pas) », l'infobulle
                      // recolle l'unité, et une graduation de six caractères sortait de
                      // la gouttière par la gauche.
                      format: (value) => num(value, 2),
                    }}
                    context={{
                      label: 'Cadence',
                      unit: 'spm',
                      values: strided.map((split) => split.cadence_spm ?? 0),
                      tone: 'effort',
                      format: (value) => `${integer(value)} spm`,
                    }}
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

          {data.context !== undefined && <Context context={data.context} />}

          {(run.total_calories != null ||
            run.active_calories != null ||
            run.elevation_m != null) && (
            <>
              <Rule>Le reste de la séance</Rule>
              <div className="grid tiles">
                {/* Les deux chiffres, **nommés**. Jamais un chiffre seul appelé
                    « calories » : une capture Apple en affiche deux — 439 actives, 492
                    totales — et elles ne veulent pas dire la même chose. Les actives
                    étaient lues à l'import puis jetées ; elles arrivent maintenant
                    jusqu'ici, ce qui était la condition pour tenir cette règle. */}
                {run.active_calories != null && (
                  <Card>
                    <Stat
                      compact
                      label="Calories actives"
                      value={integer(run.active_calories)}
                      unit="kcal"
                      detail="la dépense de la course"
                    />
                  </Card>
                )}
                {run.total_calories != null && (
                  <Card>
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
