/**
 * L'historique fusionné des courses et des séances.
 *
 * Ce n'était pas une liste mais un tableau de six colonnes — illisible à 390 px, et une
 * ligne de tableau ne se tire pas au doigt. Les colonnes reviennent en grille dès qu'il y
 * a la place : c'est la même structure qui s'aligne, pas un second rendu.
 *
 * **Chaque ligne dit ce que sa suppression emporte.** Supprimer une séance purge ses
 * séries (`ACT-04`) ; l'état armé, lui, dit « Confirmer ? » avec les mêmes mots qu'elle
 * en emporte zéro ou douze. Le compte vient du serveur et se lit **avant** d'armer — ce
 * qui vaut mieux qu'un libellé plus long dans un panneau de 96 px.
 */

import { Card, Chip, Empty, SwipeRow } from '@/components/ui';
import type { ActivityItem, ActivityOverview } from '@/features/activity/api';
import { cx } from '@/lib/cx';
import { duration, km, pace, plural, shortDate } from '@/lib/format';

import styles from '../Activity.module.css';

/** Le nom accessible d'une suppression doit désigner la ligne **et** son coût. */
function removalLabel(row: ActivityItem): string {
  const what = row.kind === 'run' ? 'la course' : 'la séance';
  const day = shortDate(row.date);
  if (row.kind !== 'workout' || row.entries === 0) return `Supprimer ${what} du ${day}`;
  return `Supprimer ${what} du ${day} et ses ${String(row.entries)} ${plural(row.entries, 'série')}`;
}

function HistoryRow({
  row,
  busy,
  onOpen,
  onEdit,
  onDuplicate,
  onRemove,
}: {
  row: ActivityItem;
  busy: boolean;
  onOpen: () => void;
  onEdit: () => void;
  onDuplicate: () => void;
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
          {row.kind === 'workout' && row.entries > 0 && (
            <span className={styles.entryDetail}>
              {' '}
              · {row.entries} {plural(row.entries, 'série')}
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

        <div className={styles.histActions}>
          {row.kind === 'workout' && (
            <Chip aria-label={`Ouvrir la séance du ${shortDate(row.date)}`} onClick={onOpen}>
              ouvrir
            </Chip>
          )}
          <Chip
            aria-label={`Corriger ${row.kind === 'run' ? 'la course' : 'la séance'} du ${shortDate(row.date)}`}
            onClick={onEdit}
          >
            corriger
          </Chip>
          {row.kind === 'workout' && (
            <Chip
              aria-label={`Dupliquer la séance du ${shortDate(row.date)}`}
              onClick={onDuplicate}
            >
              dupliquer
            </Chip>
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
  onDuplicate,
  onRemove,
}: {
  data: ActivityOverview | undefined;
  isPending: boolean;
  removing: boolean;
  onOpen: (row: ActivityItem) => void;
  onEdit: (row: ActivityItem) => void;
  onDuplicate: (row: ActivityItem) => void;
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
                onDuplicate={() => {
                  onDuplicate(row);
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
