/**
 * Créer ou corriger une activité — séance et course, dans une feuille.
 *
 * Les deux formulaires occupaient le bas de l'écran, sous quatre sections de statistiques.
 * Ils s'ouvrent maintenant depuis l'en-tête du journal, là où le geste commence. Une
 * feuille n'est pas un geste caché : elle part d'un bouton nommé, présent dans le
 * document, et au-delà de 600 px elle devient un panneau centré.
 *
 * **Un seul composant pour quatre gestes** — créer une séance, créer une course, corriger
 * l'une, corriger l'autre. Corriger n'est pas un autre formulaire : c'est le même, avec
 * une valeur de départ et un autre verbe, comme sur `/corps`. Deux formulaires
 * divergeraient au premier champ ajouté.
 *
 * La nature ne se change **qu'à la création** : une course et une séance vivent dans deux
 * fichiers, avec deux identifiants. Transformer l'une en l'autre serait une suppression
 * suivie d'une création, et rien n'annonce cela dans un formulaire de correction.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import type { ReactNode, SyntheticEvent } from 'react';

import { Button, Chip, ChipStrip, Field, Segmented, Sheet } from '@/components/ui';
import { activityApi, type Run, type Workout } from '@/features/activity/api';
import { ApiError } from '@/lib/api';
import { celebrate } from '@/lib/confetti';
import { shortDate } from '@/lib/format';
import { keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from '../Activity.module.css';
import { useInvalidateActivity } from './shared';

export type ActivityKind = 'run' | 'workout';

/**
 * La ligne à corriger, réduite à ce qui suffit pour l'ouvrir.
 *
 * Pas de jeton : la feuille relit la ligne et se sert de celui que la relecture rend.
 * Un jeton pris sur l'historique aurait pu vieillir entre l'affichage et l'appui.
 */
export interface EditTarget {
  kind: ActivityKind;
  id: number;
  date: string;
}

/** Ce que la feuille doit savoir pour s'ouvrir : une nature, et une ligne ou rien. */
export interface SheetTarget {
  kind: ActivityKind;
  editing: EditTarget | null;
}

/** Un nombre du serveur, réécrit pour un champ français (`ACT-01`). */
function fieldText(value: number | null | undefined): string {
  return value == null ? '' : String(value).replace('.', ',');
}

// ── Séance ────────────────────────────────────────────

function WorkoutForm({
  editing,
  today,
  onSaved,
  onClose,
}: {
  editing: Workout | null;
  today: string;
  onSaved: (workout: Workout) => void;
  onClose: () => void;
}) {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const { data: types } = useQuery({ queryKey: keys.activity.types(), queryFn: activityApi.types });

  const [fields, setFields] = useState({
    date: editing?.date ?? today,
    type: editing?.type ?? 'musculation',
    duration_min: fieldText(editing?.duration_min),
    rpe: editing?.rpe == null ? '' : String(editing.rpe),
    note: editing?.note ?? '',
  });
  const [error, setError] = useState<ApiError | null>(null);

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        date: fields.date,
        type: fields.type,
        duration_min: fields.duration_min,
        rpe: fields.rpe ? Number(fields.rpe) : null,
        note: fields.note || null,
      };
      return editing === null
        ? activityApi.createWorkout(payload)
        : activityApi.updateWorkout(editing.id, editing.token, payload);
    },
    onSuccess: (workout) => {
      invalidate();
      notify(
        editing === null ? 'Séance enregistrée. Ajoute tes exercices.' : 'Séance corrigée.',
        'effort',
      );
      setError(null);
      onSaved(workout);
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
      // La ligne a changé ailleurs : recharger est la seule issue honnête. La feuille,
      // elle, reste ouverte — la refermer emporterait ce qui vient d'être tapé.
      if (caught instanceof ApiError && caught.code === 'conflict') invalidate();
    },
  });

  const set = (name: keyof typeof fields) => (event: { target: { value: string } }) => {
    setFields((current) => ({ ...current, [name]: event.target.value }));
  };

  function submit(event: SyntheticEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      {error !== null && (
        <p className={styles.error} role="alert">
          {error.message}
        </p>
      )}

      <div className={styles.pair}>
        <Field
          label="Date de séance"
          type="date"
          value={fields.date}
          max={today}
          error={error?.messageFor('date')}
          onChange={set('date')}
        />
        <Field
          label="Durée de séance"
          placeholder="1h15"
          hint={editing === null ? 'approximative : elle se corrige à la fin' : undefined}
          value={fields.duration_min}
          error={error?.messageFor('duration_min')}
          onChange={set('duration_min')}
        />
      </div>

      {/* Le champ **puis** ses suggestions, dans cet ordre : une bande de pastilles
          posée avant un champ nommé « Type » se lisait comme un contrôle sans rapport
          avec lui. Le type reste libre (`ACT-03`) — les sept valeurs abrègent, elles
          ne contraignent pas.

          Des pastilles plutôt qu'une liste native : c'est la décision déjà prise pour le
          sélecteur d'exercice, et l'argument est le même — un panneau système, un
          défilement et un second appui pour choisir un mot parmi sept. */}
      <Field
        label="Type de séance"
        placeholder="escalade…"
        value={fields.type}
        error={error?.messageFor('type')}
        onChange={set('type')}
      />

      <ChipStrip label="Types proposés">
        {(types ?? []).map((type) => (
          <Chip
            key={type}
            selected={fields.type === type}
            onClick={() => {
              setFields((current) => ({ ...current, type }));
            }}
          >
            {type}
          </Chip>
        ))}
      </ChipStrip>

      <Field
        label="Effort perçu (1–10)"
        inputMode="numeric"
        placeholder="8"
        value={fields.rpe}
        error={error?.messageFor('rpe')}
        onChange={set('rpe')}
      />

      <Field
        label="Note"
        placeholder="contenu de la séance…"
        value={fields.note}
        onChange={set('note')}
      />

      <div className={styles.sheetCommit}>
        <Button
          type="submit"
          variant="primary"
          className={styles.commit}
          busy={save.isPending}
          disabled={fields.duration_min === '' || fields.type.trim() === ''}
        >
          {editing === null ? 'Enregistrer la séance' : 'Corriger la séance'}
        </Button>
        <Button variant="quiet" onClick={onClose}>
          Annuler
        </Button>
      </div>
    </form>
  );
}

// ── Course ────────────────────────────────────────────

function RunForm({
  editing,
  today,
  onSaved,
  onClose,
}: {
  editing: Run | null;
  today: string;
  onSaved: () => void;
  onClose: () => void;
}) {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();

  const [fields, setFields] = useState({
    date: editing?.date ?? today,
    distance_km: fieldText(editing?.distance_km),
    duration_min: fieldText(editing?.duration_min),
    avg_hr: editing?.avg_hr == null ? '' : String(editing.avg_hr),
    note: editing?.note ?? '',
  });
  const [error, setError] = useState<ApiError | null>(null);

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        date: fields.date,
        distance_km: fields.distance_km,
        duration_min: fields.duration_min,
        avg_hr: fields.avg_hr || null,
        note: fields.note || null,
      };
      return editing === null
        ? activityApi.createRun(payload)
        : activityApi.updateRun(editing.id, editing.token, payload);
    },
    onSuccess: () => {
      invalidate();
      if (editing === null) celebrate();
      notify(editing === null ? 'Course enregistrée.' : 'Course corrigée.', 'effort');
      setError(null);
      onSaved();
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
      if (caught instanceof ApiError && caught.code === 'conflict') invalidate();
    },
  });

  const set = (name: keyof typeof fields) => (event: { target: { value: string } }) => {
    setFields((current) => ({ ...current, [name]: event.target.value }));
  };

  function submit(event: SyntheticEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      {error !== null && (
        <p className={styles.error} role="alert">
          {error.message}
        </p>
      )}

      <div className={styles.pair}>
        <Field
          label="Date"
          type="date"
          value={fields.date}
          max={today}
          error={error?.messageFor('date')}
          onChange={set('date')}
        />
        <Field
          label="Distance"
          placeholder="8,40 ou 5mi"
          value={fields.distance_km}
          error={error?.messageFor('distance_km')}
          onChange={set('distance_km')}
        />
      </div>

      <div className={styles.pair}>
        <Field
          label="Durée"
          placeholder="44:12 ou 1h30"
          hint="mm:ss, h:mm:ss ou minutes"
          value={fields.duration_min}
          error={error?.messageFor('duration_min')}
          onChange={set('duration_min')}
        />
        <Field
          label="FC moyenne"
          inputMode="numeric"
          placeholder="152"
          value={fields.avg_hr}
          error={error?.messageFor('avg_hr')}
          onChange={set('avg_hr')}
        />
      </div>

      <Field
        label="Ressenti"
        placeholder="jambes lourdes, vent de face…"
        value={fields.note}
        onChange={set('note')}
      />

      <div className={styles.sheetCommit}>
        <Button
          type="submit"
          variant="primary"
          className={styles.commit}
          busy={save.isPending}
          disabled={fields.distance_km === '' || fields.duration_min === ''}
        >
          {editing === null ? 'Enregistrer la course' : 'Corriger la course'}
        </Button>
        <Button variant="quiet" onClick={onClose}>
          Annuler
        </Button>
      </div>
    </form>
  );
}

// ── Relecture avant correction ────────────────────────

/**
 * Relit la ligne avant de la corriger.
 *
 * Deux raisons, et la seconde est la vraie : l'historique ne porte ni la FC, ni la note,
 * ni l'effort perçu — les corriger à l'aveugle les effacerait —, et la relecture rend un
 * **jeton frais** pour la garde `If-Match`.
 */
function Loaded<T>({
  query,
  render,
}: {
  query: { data: T | undefined; isPending: boolean; error: unknown };
  render: (data: T) => ReactNode;
}) {
  if (query.error !== null && query.error !== undefined) {
    return (
      <p className={styles.error} role="alert">
        {query.error instanceof ApiError ? query.error.message : 'Activité illisible.'}
      </p>
    );
  }
  if (query.isPending || query.data === undefined) {
    return <p className={styles.empty}>chargement…</p>;
  }
  return <>{render(query.data)}</>;
}

function EditRun(props: { id: number; today: string; onSaved: () => void; onClose: () => void }) {
  const query = useQuery({
    queryKey: keys.activity.run(props.id),
    queryFn: () => activityApi.readRun(props.id),
  });

  return (
    <Loaded
      query={query}
      render={(run) => (
        <RunForm
          key={run.token}
          editing={run}
          today={props.today}
          onSaved={props.onSaved}
          onClose={props.onClose}
        />
      )}
    />
  );
}

function EditWorkout(props: {
  id: number;
  today: string;
  onSaved: (workout: Workout) => void;
  onClose: () => void;
}) {
  const query = useQuery({
    queryKey: keys.activity.workout(props.id),
    queryFn: () => activityApi.readWorkout(props.id),
  });

  return (
    <Loaded
      query={query}
      render={(workout) => (
        <WorkoutForm
          key={workout.token}
          editing={workout}
          today={props.today}
          onSaved={props.onSaved}
          onClose={props.onClose}
        />
      )}
    />
  );
}

// ── La feuille ────────────────────────────────────────

export function ActivitySheet({
  target,
  today,
  onClose,
  onSaved,
}: {
  target: SheetTarget;
  today: string;
  onClose: () => void;
  /** Rend la séance quand il y en a une : le journal s'ouvre dessus. */
  onSaved: (workout: Workout | null) => void;
}) {
  // La nature choisie dans la feuille. Elle part de celle du bouton qui l'a ouverte ;
  // l'appelant remonte la feuille à chaque ouverture, donc elle repart juste.
  const [kind, setKind] = useState<ActivityKind>(target.kind);

  const editing = target.editing;
  const title =
    editing !== null
      ? editing.kind === 'run'
        ? `Corriger la course du ${shortDate(editing.date)}`
        : `Corriger la séance du ${shortDate(editing.date)}`
      : kind === 'run'
        ? 'Nouvelle course'
        : 'Nouvelle séance';

  return (
    <Sheet
      open
      onClose={onClose}
      title={title}
      lede={
        editing !== null
          ? 'Ce qui est corrigé remplace ce qui était consigné — il n’y a pas d’annulation.'
          : 'La date et la durée suffisent. Les charges se consignent ensuite au journal.'
      }
    >
      {editing !== null ? (
        editing.kind === 'run' ? (
          <EditRun
            id={editing.id}
            today={today}
            onSaved={() => {
              onSaved(null);
            }}
            onClose={onClose}
          />
        ) : (
          <EditWorkout id={editing.id} today={today} onSaved={onSaved} onClose={onClose} />
        )
      ) : (
        <>
          <Segmented
            label="Nature de l'activité"
            value={kind}
            onChange={setKind}
            options={[
              { value: 'workout', label: 'Séance' },
              { value: 'run', label: 'Course' },
            ]}
          />
          <div className={styles.spaced}>
            {kind === 'run' ? (
              <RunForm
                editing={null}
                today={today}
                onSaved={() => {
                  onSaved(null);
                }}
                onClose={onClose}
              />
            ) : (
              <WorkoutForm editing={null} today={today} onSaved={onSaved} onClose={onClose} />
            )}
          </div>
        </>
      )}
    </Sheet>
  );
}
