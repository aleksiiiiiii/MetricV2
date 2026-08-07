import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  Badge,
  Button,
  Card,
  Check,
  CheckGroup,
  Empty,
  Field,
  PageHead,
  Progress,
  Ring,
  Rule,
  Sparkline,
  Stat,
} from '@/components/ui';
import {
  routineApi,
  type ChecklistItem,
  type ChecklistView,
  type Supplement,
} from '@/features/routine/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { integer, longDate, num, plural, time, volume } from '@/lib/format';
import { CROSS_CUTTING, keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from './Routine.module.css';

/** Découpage de la journée, repris de la charte (section 08). */
const MOMENTS = [
  { label: 'Matin', until: '11:59' },
  { label: 'Journée', until: '17:59' },
  { label: 'Soir', until: '23:59' },
] as const;

function momentOf(clock: string): string {
  return MOMENTS.find((moment) => clock <= moment.until)?.label ?? 'Soir';
}

function useInvalidateRoutine() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: keys.hydration.all() });
    void client.invalidateQueries({ queryKey: keys.supplements.all() });
    for (const key of CROSS_CUTTING) void client.invalidateQueries({ queryKey: key });
  };
}

// ── Hydratation ───────────────────────────────────────

function Hydration() {
  const client = useQueryClient();
  const invalidate = useInvalidateRoutine();
  const { notify } = useToast();

  const { data } = useQuery({
    queryKey: keys.hydration.all(),
    queryFn: () => routineApi.hydration(),
  });

  const drink = useMutation({
    mutationFn: (millilitres: number) => routineApi.drink(millilitres),
    onSuccess: () => {
      invalidate();
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Enregistrement impossible.', 'recover');
    },
  });

  const undrink = useMutation({
    mutationFn: ({ id, token }: { id: number; token: string }) => routineApi.undrink(id, token),
    onSuccess: () => {
      invalidate();
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Suppression impossible.', 'recover');
      void client.invalidateQueries({ queryKey: keys.hydration.all() });
    },
  });

  const stats = data?.stats;

  return (
    <Card>
      <div className="spread">
        <div>
          <h3>Hydratation</h3>
          <p className={styles.note}>
            Un volume, un geste. La prise est horodatée à l'instant du clic.
          </p>
        </div>
        {stats && (
          <Badge tone={stats.today_ml >= stats.target_ml ? 'effort' : 'signal'} mono>
            {volume(stats.today_ml)} / {volume(stats.target_ml)}
          </Badge>
        )}
      </div>

      <div className={styles.hydration}>
        {stats && (
          <Ring
            // Journée pas encore commencée : l'anneau reste vide plutôt que d'écrire
            // « 0 % ». C'est la même règle que sur `/nutrition` et que le tiret du
            // tableau de bord — un jour qui débute n'est pas un objectif manqué, et la
            // charte tient déjà ce discours sur la grille d'assiduité.
            ratio={stats.today_ml > 0 ? stats.ratio : null}
            label="Objectif du jour"
            detail={
              stats.average_7d_ml !== null
                ? `moyenne 7 j : ${volume(stats.average_7d_ml)}`
                : undefined
            }
            tone={stats.today_ml >= stats.target_ml ? 'effort' : 'signal'}
          />
        )}

        <div className={styles.presets}>
          {(data?.presets_ml ?? []).map((millilitres) => (
            <button
              key={millilitres}
              type="button"
              className={styles.preset}
              disabled={drink.isPending}
              onClick={() => {
                drink.mutate(millilitres);
              }}
            >
              + {integer(millilitres)} ml
            </button>
          ))}
        </div>
      </div>

      {data && data.today.length > 0 && (
        <div className={styles.intakes}>
          {data.today.map((intake) => (
            <span className={styles.intake} key={intake.id}>
              {time(intake.datetime)} · {integer(intake.volume_ml)} ml
              <button
                type="button"
                className={styles.remove}
                aria-label={`Supprimer la prise de ${time(intake.datetime)}`}
                onClick={() => {
                  undrink.mutate({ id: intake.id, token: intake.token });
                }}
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}

      {data && data.series.length > 1 && (
        <Sparkline
          values={data.series.map((day) => day.volume_ml)}
          tone="signal"
          label="Volume bu sur 30 jours"
        />
      )}
    </Card>
  );
}

// ── Checklist des suppléments ─────────────────────────

function Checklist() {
  const client = useQueryClient();
  const invalidate = useInvalidateRoutine();
  const { notify } = useToast();

  const { data, isPending } = useQuery({
    queryKey: keys.supplements.today(),
    queryFn: routineApi.checklist,
  });

  /**
   * Bascule optimiste (`SUP-04`).
   *
   * L'état est appliqué localement avant la réponse du serveur, et **restauré** en cas
   * d'échec. C'est ce qui rend la checklist utilisable : attendre un aller-retour vers
   * Nextcloud pour voir une case se cocher condamnerait la saisie en un geste.
   */
  const toggle = useMutation({
    mutationFn: (item: ChecklistItem) =>
      item.taken ? routineApi.untake(item.schedule_id) : routineApi.take(item.schedule_id),

    onMutate: async (item: ChecklistItem) => {
      const key = keys.supplements.today();
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<ChecklistView>(key);

      client.setQueryData<ChecklistView>(key, (current) => {
        if (!current) return current;
        const items = current.items.map((entry) =>
          entry.schedule_id === item.schedule_id ? { ...entry, taken: !entry.taken } : entry,
        );
        const taken = items.filter((entry) => entry.taken).length;
        return {
          ...current,
          items,
          ratio: {
            taken,
            planned: items.length,
            ratio: items.length > 0 ? taken / items.length : 0,
            complete: items.length > 0 && taken === items.length,
          },
        };
      });

      return { previous };
    },

    onError: (caught: unknown, _item, context) => {
      // Restauration : l'écran ne doit jamais rester sur un état que le serveur a refusé.
      if (context?.previous) client.setQueryData(keys.supplements.today(), context.previous);
      notify(caught instanceof ApiError ? caught.message : 'Bascule impossible.', 'recover');
    },

    onSuccess: (view) => {
      // Le serveur renvoie la checklist complète : séries et ratio arrivent recalculés.
      client.setQueryData(keys.supplements.today(), view);
      invalidate();
    },
  });

  const items = data?.items ?? [];
  const grouped = MOMENTS.map((moment) => ({
    label: moment.label,
    items: items.filter((item) => momentOf(item.time) === moment.label),
  })).filter((group) => group.items.length > 0);

  return (
    <Card>
      <div className="spread">
        <div>
          <h3>{longDate(new Date())}</h3>
          <p className={cx('eyebrow', styles.tightEyebrow)}>
            {data?.ratio.complete === true ? 'journée complète' : 'checklist du jour'}
          </p>
        </div>
        {data && (
          <Badge tone={data.ratio.complete ? 'effort' : 'signal'}>
            {data.ratio.taken}/{data.ratio.planned}
          </Badge>
        )}
      </div>

      {isPending ? (
        <p className={cx(styles.empty, styles.emptyInset)}>chargement…</p>
      ) : items.length === 0 ? (
        <Empty title="Aucun supplément au planning">
          Ajoute ce que tu prends, et la checklist se remplit toute seule chaque matin.
        </Empty>
      ) : (
        <>
          {grouped.map((group) => (
            <CheckGroup title={group.label} key={group.label}>
              {group.items.map((item) => (
                <Check
                  key={item.schedule_id}
                  label={item.name}
                  dose={`${num(item.dose, 1)} ${item.unit} · ${item.time}`}
                  streak={item.streak > 0 ? `${item.streak} j` : undefined}
                  checked={item.taken}
                  onToggle={() => {
                    toggle.mutate(item);
                  }}
                />
              ))}
            </CheckGroup>
          ))}
          <Progress done={data?.ratio.taken ?? 0} total={data?.ratio.planned ?? 0} />
        </>
      )}
    </Card>
  );
}

// ── Planning ──────────────────────────────────────────

const CADENCES = [
  { value: 'daily', label: 'tous les jours' },
  { value: 'window:min_count=1;window_days=2', label: 'un jour sur deux' },
  { value: 'window:min_count=1;window_days=3', label: 'un jour sur trois' },
  { value: 'per_week:count=3', label: '3 fois par semaine' },
  { value: 'none', label: 'sans attente' },
] as const;

function Schedule() {
  const invalidate = useInvalidateRoutine();
  const { notify } = useToast();

  const { data: units } = useQuery({
    queryKey: keys.supplements.units(),
    queryFn: routineApi.units,
  });
  const { data: schedule } = useQuery({
    queryKey: keys.supplements.schedule(),
    queryFn: routineApi.schedule,
  });

  const [fields, setFields] = useState({
    name: '',
    dose: '',
    unit: 'g',
    time: '08:00',
    frequency: 'daily',
  });
  const [error, setError] = useState<ApiError | null>(null);

  const add = useMutation({
    mutationFn: () =>
      routineApi.addSupplement({
        name: fields.name,
        dose: Number.parseFloat(fields.dose.replace(',', '.')),
        unit: fields.unit,
        time: fields.time,
        frequency: fields.frequency,
      }),
    onSuccess: () => {
      invalidate();
      notify('Supplément ajouté au planning.', 'effort');
      setFields((current) => ({ ...current, name: '', dose: '' }));
      setError(null);
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
    },
  });

  const remove = useMutation({
    mutationFn: (item: Supplement) => routineApi.removeSupplement(item.id, item.token),
    onSuccess: () => {
      invalidate();
      notify("Retiré du planning. L'historique des prises est conservé.", 'signal');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Retrait impossible.', 'recover');
    },
  });

  const set = (name: keyof typeof fields) => (event: { target: { value: string } }) => {
    setFields((current) => ({ ...current, [name]: event.target.value }));
  };

  return (
    <Card>
      <h3>Planning</h3>
      <p className={styles.note}>
        La cadence vit ici et nulle part ailleurs : la grille d'assiduité la lira au même endroit,
        elles ne pourront pas diverger.
      </p>

      {(schedule ?? []).map((item) => (
        <div className={styles.scheduleRow} key={item.schedule_id}>
          <span>
            {item.name}
            <span className={styles.moment}>
              {num(item.dose, 1)} {item.unit} · {item.time}
            </span>
            <br />
            <span className={styles.cadence}>{item.cadence_label}</span>
          </span>
          <button
            type="button"
            className={styles.remove}
            aria-label={`Retirer ${item.name} du planning`}
            onClick={() => {
              remove.mutate(item);
            }}
          >
            ✕
          </button>
        </div>
      ))}

      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          add.mutate();
        }}
        noValidate
      >
        {error !== null && (
          <p className={styles.error} role="alert">
            {error.message}
          </p>
        )}

        <Field
          label="Nom"
          placeholder="Créatine"
          value={fields.name}
          error={error?.messageFor('name')}
          onChange={set('name')}
        />

        <div className={styles.pair}>
          <Field
            label="Dose"
            inputMode="decimal"
            placeholder="5"
            value={fields.dose}
            error={error?.messageFor('dose')}
            onChange={set('dose')}
          />
          <div className="field">
            <label htmlFor="supplement-unit" className="sr-only">
              Unité
            </label>
            <Field
              label="Unité"
              list="supplement-units"
              value={fields.unit}
              onChange={set('unit')}
            />
            <datalist id="supplement-units">
              {(units ?? []).map((unit) => (
                <option value={unit} key={unit} />
              ))}
            </datalist>
          </div>
        </div>

        <div className={styles.pair}>
          <Field label="Moment" type="time" value={fields.time} onChange={set('time')} />
          <Field
            label="Cadence"
            list="supplement-cadences"
            value={
              CADENCES.find((item) => item.value === fields.frequency)?.label ?? fields.frequency
            }
            onChange={(event) => {
              const match = CADENCES.find((item) => item.label === event.target.value);
              setFields((current) => ({
                ...current,
                frequency: match?.value ?? event.target.value,
              }));
            }}
          />
          <datalist id="supplement-cadences">
            {CADENCES.map((item) => (
              <option value={item.label} key={item.value} />
            ))}
          </datalist>
        </div>

        <Button
          type="submit"
          variant="ghost"
          busy={add.isPending}
          disabled={fields.name.trim() === '' || fields.dose === ''}
        >
          Ajouter au planning
        </Button>
      </form>
    </Card>
  );
}

// ── Écran ─────────────────────────────────────────────

export function Routine() {
  const { data: hydration } = useQuery({
    queryKey: keys.hydration.all(),
    queryFn: () => routineApi.hydration(),
  });

  const stats = hydration?.stats;

  return (
    <div className="wrap">
      <PageHead eyebrow="Routine du jour" title={<>Hydratation &amp; suppléments</>} />

      <Rule>Aujourd'hui</Rule>
      <div className={styles.split}>
        <div className="stack">
          <Hydration />
          <Checklist />
        </div>

        <div className="stack">
          <Card>
            <Stat
              label="Moyenne · 7 jours"
              value={stats?.average_7d_ml != null ? volume(stats.average_7d_ml) : '—'}
              detail={
                stats
                  ? `objectif atteint ${stats.days_reached} ${plural(stats.days_reached, 'jour')} sur ${stats.days_counted}`
                  : undefined
              }
            />
          </Card>

          <Schedule />
        </div>
      </div>
    </div>
  );
}
