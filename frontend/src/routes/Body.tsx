import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import type { SyntheticEvent } from 'react';

import {
  Badge,
  Button,
  Card,
  Chart,
  Empty,
  Field,
  PageHead,
  Rule,
  Stat,
  Table,
} from '@/components/ui';
import type { Column } from '@/components/ui';
import {
  bodyApi,
  type MeasurementIndicator,
  type WeightEntry,
  type WeightPayload,
} from '@/features/body/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { delta, isoDay, kg, num, plural, shortDate } from '@/lib/format';
import { CROSS_CUTTING, keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from './Body.module.css';

/** Nombre de points affichés sur la courbe. Au-delà, la tendance devient illisible. */
const CHART_POINTS = 60;

function useInvalidateBody() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: keys.body.all() });
    // Une pesée nourrit le tableau de bord et la piste d'assiduité de saisie.
    for (const key of CROSS_CUTTING) void client.invalidateQueries({ queryKey: key });
  };
}

// ── Saisie d'une pesée ────────────────────────────────

function WeightForm({ editing, onDone }: { editing: WeightEntry | null; onDone: () => void }) {
  const invalidate = useInvalidateBody();
  const { notify } = useToast();

  const [day, setDay] = useState(() => editing?.date ?? isoDay(new Date()));
  const [weight, setWeight] = useState(() => editing?.weight_kg.toString() ?? '');
  const [note, setNote] = useState(() => editing?.note ?? '');
  const [error, setError] = useState<ApiError | null>(null);

  const save = useMutation({
    mutationFn: (payload: WeightPayload) =>
      editing
        ? bodyApi.updateWeight(editing.id, editing.token, payload)
        : bodyApi.createWeight(payload),
    onSuccess: () => {
      invalidate();
      notify(editing ? 'Pesée corrigée.' : 'Pesée enregistrée.', 'effort');
      setWeight('');
      setNote('');
      setError(null);
      onDone();
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
      if (caught instanceof ApiError && caught.code === 'conflict') {
        // La ligne a changé ailleurs : recharger est la seule issue honnête.
        invalidate();
      }
    },
  });

  function submit(event: SyntheticEvent) {
    event.preventDefault();
    // La virgule décimale est ce qu'on tape naturellement en français.
    const value = Number.parseFloat(weight.replace(',', '.'));
    if (Number.isNaN(value)) {
      setError(null);
      return;
    }
    save.mutate({ date: day, weight_kg: value, note: note.trim() || null });
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      {error !== null && (
        <p className={styles.error} role="alert">
          {error.message}
        </p>
      )}

      <div className={styles.formRow}>
        <Field
          label="Date"
          type="date"
          value={day}
          max={isoDay(new Date())}
          error={error?.messageFor('date')}
          onChange={(event) => {
            setDay(event.target.value);
          }}
        />
        <Field
          label="Poids (kg)"
          inputMode="decimal"
          placeholder="68,4"
          value={weight}
          error={error?.messageFor('weight_kg')}
          onChange={(event) => {
            setWeight(event.target.value);
          }}
        />
      </div>

      <Field
        label="Note"
        placeholder="à jeun, après séance…"
        value={note}
        error={error?.messageFor('note')}
        onChange={(event) => {
          setNote(event.target.value);
        }}
      />

      <div className="row">
        <Button type="submit" variant="primary" busy={save.isPending} disabled={weight === ''}>
          {editing ? 'Corriger la pesée' : 'Enregistrer la pesée'}
        </Button>
        {editing && (
          <Button variant="quiet" onClick={onDone}>
            Annuler
          </Button>
        )}
      </div>
    </form>
  );
}

// ── Mensurations ──────────────────────────────────────

function Indicator({ indicator }: { indicator: MeasurementIndicator }) {
  return (
    <div className={styles.indicator}>
      <div className={styles.indicatorLabel}>{indicator.label}</div>
      {indicator.latest === null ? (
        <div className={styles.indicatorValue}>
          <span className={styles.empty}>—</span>
        </div>
      ) : (
        <>
          <div className={styles.indicatorValue}>
            {num(indicator.latest, 1)}
            <span className={styles.indicatorUnit}>{indicator.unit}</span>
          </div>
          <div
            className={cx(
              styles.indicatorDelta,
              indicator.direction && styles[indicator.direction],
            )}
          >
            {indicator.delta === null
              ? 'premier relevé'
              : `${delta(indicator.delta)} ${indicator.unit}`}
          </div>
        </>
      )}
    </div>
  );
}

function MeasurementPanel() {
  const invalidate = useInvalidateBody();
  const { notify } = useToast();
  const [values, setValues] = useState<Record<string, string>>({});
  const [day, setDay] = useState(() => isoDay(new Date()));
  const [error, setError] = useState<ApiError | null>(null);

  const { data } = useQuery({
    queryKey: keys.body.measurements(),
    queryFn: () => bodyApi.measurements(),
  });

  const save = useMutation({
    mutationFn: () => {
      const numeric = Object.fromEntries(
        Object.entries(values)
          .filter(([, raw]) => raw.trim() !== '')
          .map(([field, raw]) => [field, Number.parseFloat(raw.replace(',', '.'))]),
      );
      return bodyApi.createMeasurement({ date: day, ...numeric });
    },
    onSuccess: () => {
      invalidate();
      notify('Mensurations enregistrées.', 'effort');
      setValues({});
      setError(null);
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
    },
  });

  const indicators = data?.indicators ?? [];
  const nothingFilled = Object.values(values).every((raw) => raw.trim() === '');

  return (
    <Card>
      <h3>Mensurations</h3>
      <p className={styles.note}>
        Toutes facultatives — on ne mesure pas tout à chaque fois. Chaque mesure garde son propre
        historique.
      </p>

      <div className={styles.indicators}>
        {indicators.map((indicator) => (
          <Indicator indicator={indicator} key={indicator.field} />
        ))}
      </div>

      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
        noValidate
      >
        {error !== null && (
          <p className={styles.error} role="alert">
            {error.message}
          </p>
        )}

        <Field
          label="Date"
          type="date"
          value={day}
          max={isoDay(new Date())}
          onChange={(event) => {
            setDay(event.target.value);
          }}
        />

        <div className={styles.formRow}>
          {indicators.map((indicator) => (
            <Field
              key={indicator.field}
              label={`${indicator.label} (${indicator.unit})`}
              inputMode="decimal"
              value={values[indicator.field] ?? ''}
              error={error?.messageFor(indicator.field)}
              onChange={(event) => {
                setValues((current) => ({ ...current, [indicator.field]: event.target.value }));
              }}
            />
          ))}
        </div>

        <Button type="submit" variant="ghost" busy={save.isPending} disabled={nothingFilled}>
          Enregistrer les mensurations
        </Button>
      </form>
    </Card>
  );
}

// ── Écran ─────────────────────────────────────────────

export function Body() {
  const invalidate = useInvalidateBody();
  const { notify } = useToast();
  const [editing, setEditing] = useState<WeightEntry | null>(null);

  const { data, isPending, error } = useQuery({
    queryKey: keys.body.weight(),
    queryFn: () => bodyApi.weight(),
  });

  const remove = useMutation({
    mutationFn: (entry: WeightEntry) => bodyApi.deleteWeight(entry.id, entry.token),
    onSuccess: () => {
      invalidate();
      notify('Pesée supprimée.', 'signal');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Suppression impossible.', 'recover');
      invalidate();
    },
  });

  const columns: Column<WeightEntry>[] = [
    { key: 'date', header: 'Date', numeric: true, render: (row) => shortDate(row.date) },
    { key: 'weight', header: 'Poids', numeric: true, render: (row) => kg(row.weight_kg) },
    {
      key: 'note',
      header: 'Note',
      render: (row) => row.note ?? <span className={styles.empty}>—</span>,
    },
    {
      key: 'source',
      header: 'Source',
      render: (row) =>
        row.source === 'manual' ? (
          <span className={styles.empty}>saisie</span>
        ) : (
          <Badge tone="signal">{row.source}</Badge>
        ),
    },
    {
      key: 'actions',
      header: '',
      render: (row) => (
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.iconButton}
            aria-label={`Corriger la pesée du ${shortDate(row.date)}`}
            onClick={() => {
              setEditing(row);
            }}
          >
            corriger
          </button>
          <button
            type="button"
            className={cx(styles.iconButton, styles.danger)}
            aria-label={`Supprimer la pesée du ${shortDate(row.date)}`}
            onClick={() => {
              remove.mutate(row);
            }}
          >
            supprimer
          </button>
        </div>
      ),
    },
  ];

  const stats = data?.stats;
  const series = (data?.series ?? []).slice(-CHART_POINTS);

  /**
   * Tant que la requête n'a pas répondu, l'écran ne sait rien — et « aucune pesée » est
   * une affirmation, pas une absence de réponse. Les quatre tuiles l'écrivaient pendant
   * la seconde de chargement, avant de la remplacer par la vraie valeur : le premier
   * regard tombait sur un écran qui déclare vide un historique qu'il n'a pas encore lu.
   */
  const waiting = stats === undefined;

  return (
    <div className="wrap">
      <PageHead eyebrow="Domaine Corps" title={<>Poids &amp; mensurations</>} />

      <Rule>Indicateurs</Rule>

      {error !== null && (
        <p className={styles.error} role="alert">
          {error instanceof ApiError ? error.message : 'Impossible de charger le domaine Corps.'}
        </p>
      )}

      {/* Des tuiles : un libellé, un chiffre, une ligne. Empilées, il fallait faire
          défiler pour comparer deux nombres qui se lisent d'un même coup d'œil. */}
      <div className="grid tiles">
        <Card>
          <Stat
            compact
            label="Dernier poids"
            value={
              stats?.latest_kg !== null && stats !== undefined ? num(stats.latest_kg ?? 0, 1) : '—'
            }
            unit={stats?.latest_kg != null ? 'kg' : undefined}
            detail={
              waiting
                ? 'chargement…'
                : stats.latest_date != null
                  ? shortDate(stats.latest_date)
                  : 'aucune pesée'
            }
          />
        </Card>
        <Card>
          <Stat
            compact
            label="Variation · 8 pesées"
            value={stats?.change_kg != null ? delta(stats.change_kg) : '—'}
            unit={stats?.change_kg != null ? 'kg' : undefined}
            detail={
              waiting
                ? 'chargement…'
                : stats.change_kg != null
                  ? stats.change_kg <= 0
                    ? 'en baisse'
                    : 'en hausse'
                  : 'pas assez de relevés'
            }
            direction={
              stats?.change_kg != null ? (stats.change_kg <= 0 ? 'up' : 'down') : undefined
            }
          />
        </Card>
        <Card>
          <Stat
            compact
            label="Écart à l'objectif"
            value={stats?.to_target_kg != null ? delta(stats.to_target_kg) : '—'}
            unit={stats?.to_target_kg != null ? 'kg' : undefined}
            detail={stats !== undefined ? `objectif ${num(stats.target_kg, 1)} kg` : undefined}
          />
        </Card>
        <Card>
          <Stat
            compact
            label="Amplitude"
            value={stats?.amplitude_kg != null ? num(stats.amplitude_kg, 1) : '—'}
            unit={stats?.amplitude_kg != null ? 'kg' : undefined}
            detail={
              waiting
                ? 'chargement…'
                : stats.min_kg != null && stats.max_kg != null
                  ? `${num(stats.min_kg, 1)} → ${num(stats.max_kg, 1)} kg`
                  : `${stats.count} ${plural(stats.count, 'relevé')}`
            }
          />
        </Card>
      </div>

      <Rule>Courbe</Rule>
      <Card>
        {series.length < 2 ? (
          <Empty title="Pas encore de courbe">Deux pesées suffisent à tracer une tendance.</Empty>
        ) : (
          <Chart
            labels={series.map((point) => shortDate(point.date))}
            primary={{
              label: 'Poids',
              unit: 'kg',
              values: series.map((point) => point.weight_kg),
              tone: 'signal',
              format: (value) => num(value, 1),
            }}
            overlays={[
              {
                label: 'Tendance 7 j',
                unit: 'kg',
                // La tendance vient du serveur : le client ne recalcule aucune moyenne.
                values: series.map((point) => point.trend_kg ?? point.weight_kg),
                tone: 'effort',
                dashed: true,
              },
            ]}
            labelEvery={Math.max(1, Math.ceil(series.length / 6))}
          />
        )}
      </Card>

      <Rule>Saisie et historique</Rule>
      <div className={styles.grid}>
        <Card flush>
          <h3 className={styles.flushTitle}>
            Historique {data !== undefined && <span className={styles.empty}>· {data.total}</span>}
          </h3>
          {isPending ? (
            <p className={cx(styles.empty, styles.flushPad)}>chargement…</p>
          ) : data && data.entries.length > 0 ? (
            <Table
              columns={columns}
              rows={data.entries}
              rowKey={(row) => `${row.id}-${row.token}`}
              caption="Historique des pesées"
            />
          ) : (
            <div className={styles.flushPad}>
              <Empty title="Aucune pesée">Un chiffre le matin, et la courbe commence.</Empty>
            </div>
          )}
        </Card>

        <div className="stack">
          <Card>
            <h3>{editing ? 'Corriger la pesée' : 'Nouvelle pesée'}</h3>
            <WeightForm
              key={editing?.token ?? 'new'}
              editing={editing}
              onDone={() => {
                setEditing(null);
              }}
            />
          </Card>

          <MeasurementPanel />
        </div>
      </div>
    </div>
  );
}
