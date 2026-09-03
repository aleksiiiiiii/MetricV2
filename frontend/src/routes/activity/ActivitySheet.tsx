/**
 * Créer ou corriger une course, dans une feuille.
 *
 * Le formulaire occupait le bas de l'écran, sous quatre sections de statistiques. Il
 * s'ouvre maintenant depuis un bouton nommé, là où le geste commence. Une feuille n'est
 * pas un geste caché : elle part d'un élément présent dans le document, et au-delà de
 * 600 px elle devient un panneau centré.
 *
 * **Un seul composant pour deux gestes** — créer, corriger. Corriger n'est pas un autre
 * formulaire : c'est le même, avec une valeur de départ et un autre verbe, comme sur
 * `/corps`. Deux formulaires divergeraient au premier champ ajouté.
 *
 * **Le sélecteur de nature a disparu, pas le fichier.** La feuille servait aussi à saisir
 * une séance de musculation ; la phase 5 de `docs/refonte-activite.md` l'a supprimée, et
 * il ne reste qu'une nature à créer à la main. Le plan rangeait ce fichier parmi ceux qui
 * partaient — à tort : il portait la saisie de la course, que **R1** protège. C'est sa
 * moitié séance qui est partie.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import type { ReactNode, SyntheticEvent } from 'react';

import { Button, Field, Sheet } from '@/components/ui';
import { activityApi, type Run } from '@/features/activity/api';
import { ApiError } from '@/lib/api';
import { celebrate } from '@/lib/confetti';
import { shortDate } from '@/lib/format';
import { keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from '../Activity.module.css';
import { useInvalidateActivity } from './shared';

/**
 * La ligne à corriger, réduite à ce qui suffit pour l'ouvrir.
 *
 * Pas de jeton : la feuille relit la ligne et se sert de celui que la relecture rend.
 * Un jeton pris sur l'historique aurait pu vieillir entre l'affichage et l'appui.
 */
export interface EditTarget {
  kind: 'run';
  id: number;
  date: string;
}

/**
 * Ce que la feuille doit savoir pour s'ouvrir : une ligne, ou rien.
 *
 * `kind` a survécu à la disparition de la séance, et volontairement : l'appelant nomme ce
 * qu'il ouvre, et le jour où une deuxième nature reviendrait, c'est ici qu'elle se
 * déclarerait plutôt que dans un booléen qui ne dit rien.
 */
export interface SheetTarget {
  kind: 'run';
  editing: EditTarget | null;
}

/** Un nombre du serveur, réécrit pour un champ français (`ACT-01`). */
function fieldText(value: number | null | undefined): string {
  return value == null ? '' : String(value).replace('.', ',');
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

// ── La feuille ────────────────────────────────────────

export function ActivitySheet({
  target,
  today,
  onClose,
}: {
  target: SheetTarget;
  today: string;
  onClose: () => void;
}) {
  const editing = target.editing;

  return (
    <Sheet
      open
      onClose={onClose}
      title={
        editing !== null ? `Corriger la course du ${shortDate(editing.date)}` : 'Nouvelle course'
      }
      lede={
        editing !== null
          ? 'Ce qui est corrigé remplace ce qui était consigné — il n’y a pas d’annulation.'
          : 'Le temps et l’allure suffisent : la distance s’en déduit.'
      }
    >
      {editing !== null ? (
        <EditRun id={editing.id} today={today} onSaved={onClose} onClose={onClose} />
      ) : (
        <RunForm editing={null} today={today} onSaved={onClose} onClose={onClose} />
      )}
    </Sheet>
  );
}
