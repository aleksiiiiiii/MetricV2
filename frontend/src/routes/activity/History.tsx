/**
 * L'historique fusionné des courses et des séances tabata.
 *
 * Ce n'était pas une liste mais un tableau de six colonnes — illisible à 390 px, et une
 * ligne de tableau ne se tire pas au doigt. Les colonnes reviennent en grille dès qu'il y
 * a la place : c'est la même structure qui s'aligne, pas un second rendu.
 *
 * **C'est ici que « qu'est-ce que j'ai fait la semaine dernière » se lit.** La musculation
 * saisie série par série a disparu avec son journal ; ce qui reste sur cet écran est cette
 * liste, et elle est devenue la seule réponse à la question. Le §8 de
 * `docs/refonte-activite.md` laissait le choix entre la supprimer et la rebrancher : elle
 * est rebranchée.
 *
 * **Chaque ligne dit ce que sa suppression emporte.** Supprimer une séance purge ses
 * séries (`ACT-04`), et l'état armé le dit avant que le second appui ne l'exécute.
 */

import { Card, Chip, Empty, SwipeRow } from '@/components/ui';
import type { ActivityItem, ActivityOverview } from '@/features/activity/api';
import { cx } from '@/lib/cx';
import { duration, km, pace, plural, shortDate } from '@/lib/format';

import styles from '../Activity.module.css';

/**
 * Le nom accessible d'une suppression doit désigner la ligne **et** son coût.
 *
 * Le nombre de séries n'y figure pas, et c'est délibéré : la réponse du serveur porte les
 * **rounds** de la séance, pas le compte de ses lignes de série. Écrire « et ses 4
 * séries » là où quatre est un nombre de tours serait une valeur inventée — le genre que
 * l'écran affiche sans broncher et que personne ne vient corriger.
 */
function removalLabel(row: ActivityItem): string {
  const day = shortDate(row.date);
  if (row.kind === 'run') return `Supprimer la course du ${day}`;
  return `Supprimer la séance « ${row.label} » du ${day} et ses séries`;
}

function HistoryRow({
  row,
  busy,
  onOpen,
  onEdit,
  onRemove,
}: {
  row: ActivityItem;
  busy: boolean;
  onOpen: () => void;
  onEdit: () => void;
  onRemove: () => void;
}) {
  return (
    <SwipeRow actionLabel={removalLabel(row)} busy={busy} onAction={onRemove}>
      <div className={styles.histRow}>
        <span className={styles.histDate}>{shortDate(row.date)}</span>
        <span className={styles.histLabel}>
          {row.label}
          {/* Le serveur nomme déjà une course « Course » : répéter le mot faisait
              lire « Course · course ». Le suffixe ne sert que si le libellé se tait. */}
          {row.kind === 'run' && row.label.toLowerCase() !== 'course' && (
            <span className={styles.entryDetail}> · course</span>
          )}
          {/* Des **rounds**, et non des séries : c'est ce que la séance a joué, et c'est
              le seul des deux nombres que la réponse porte. */}
          {row.kind === 'workout' && row.entries > 0 && (
            <span className={styles.entryDetail}>
              {' '}
              · {row.entries} {plural(row.entries, 'round')}
            </span>
          )}
        </span>

        {/* Le tiret est une **colonne vide**, pas une information. Il tient sa place
            tant qu'il y a des colonnes à aligner ; sur une fiche à 390 px, il ne
            laisserait qu'un trait orphelin sous la date. */}
        {row.distance_km !== null ? (
          <span className={styles.histNum}>{km(row.distance_km)}</span>
        ) : (
          <span className={cx(styles.histNum, styles.histNone)}>—</span>
        )}
        <span className={styles.histNum}>{duration(row.duration_min)}</span>
        {row.pace_min_km !== null ? (
          <span className={styles.histNum}>{pace(row.pace_min_km)}</span>
        ) : (
          <span className={cx(styles.histNum, styles.histNone)}>—</span>
        )}

        {/* **Une séance n'a plus ni « ouvrir » ni « corriger ».** Il n'y a plus de journal
            à ouvrir en place, et le serveur n'a aucune route pour la modifier : elle dit
            ce que Cadence a joué. Ce qui se corrige, c'est le circuit qui la produit, sur
            `/activite/seances`. Une puce qui ouvrirait une feuille vide serait pire que
            son absence. */}
        <div className={styles.histActions}>
          {row.kind === 'run' && (
            <>
              {/* « détail » et non « ouvrir » : une course mène à sa page de paliers. */}
              <Chip
                aria-label={`Voir le détail de la course du ${shortDate(row.date)}`}
                onClick={onOpen}
              >
                détail
              </Chip>
              <Chip aria-label={`Corriger la course du ${shortDate(row.date)}`} onClick={onEdit}>
                corriger
              </Chip>
            </>
          )}
        </div>
      </div>
    </SwipeRow>
  );
}

export function History({
  data,
  isPending,
  removing,
  onOpen,
  onEdit,
  onRemove,
}: {
  data: ActivityOverview | undefined;
  isPending: boolean;
  removing: boolean;
  onOpen: (row: ActivityItem) => void;
  onEdit: (row: ActivityItem) => void;
  onRemove: (row: ActivityItem) => void;
}) {
  return (
    <Card flush>
      <h3 className={styles.flushTitle}>
        Historique {data !== undefined && <span className={styles.empty}>· {data.total}</span>}
      </h3>

      {isPending ? (
        <p className={cx(styles.empty, styles.flushPad)}>chargement…</p>
      ) : data && data.history.length > 0 ? (
        <ul className={styles.history} aria-label="Historique des activités">
          {data.history.map((row) => (
            <li key={`${row.kind}-${String(row.id)}-${row.token}`}>
              <HistoryRow
                row={row}
                busy={removing}
                onOpen={() => {
                  onOpen(row);
                }}
                onEdit={() => {
                  onEdit(row);
                }}
                onRemove={() => {
                  onRemove(row);
                }}
              />
            </li>
          ))}
        </ul>
      ) : (
        <div className={styles.flushPad}>
          <Empty title="Aucune activité">
            Une sortie, une séance — la semaine commence à compter.
          </Empty>
        </div>
      )}
    </Card>
  );
}
