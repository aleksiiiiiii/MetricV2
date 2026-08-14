/**
 * Saisir une séance par ses notes, ou par une photo du carnet (`C07`).
 *
 * On colle « développé couché 4x8 60kg / tractions 3xmax », ou on photographie la page, et
 * un tableau en sort. **Rien n'est écrit avant que chaque ligne ait été acceptée.**
 *
 * ## Trois façons dont une ligne coûte quelque chose
 *
 * Elles ne sont pas au même prix, et c'est pour cela que l'écran les distingue :
 *
 * * **reconnu** — l'exercice existe au catalogue, sous ce nom ou sous un alias déjà appris.
 *   Rien à écrire, rien à valider : la ligne s'ajoute à la séance et c'est tout.
 * * **à rapprocher** — le modèle pense que « DC barre » est le « Développé couché » du
 *   catalogue. Accepter ajoute une **graphie** à cet exercice ; le nom du catalogue reste
 *   celui qui s'affiche et qui s'écrit. Une fusion erronée est difficile à défaire.
 * * **à créer** — absent du catalogue. Accepter crée une entrée, avec le groupe déduit.
 *
 * Les deux dernières portent un bouton **par ligne**. Un « tout accepter » ferait de la
 * validation une formalité, ce qui est exactement ce que le ticket interdit.
 *
 * ## Ce qui reste vide, et pourquoi
 *
 * Une charge écrite dans une autre unité que le kilogramme **n'est pas convertie** : la
 * ligne le dit, et le champ se retape. Convertir une lecture de modèle produirait un
 * nombre d'apparence honnête que personne n'a soulevé. Le poids du corps, lui, vaut zéro —
 * c'est une mesure du domaine (`ACT-07`), pas une absence.
 */

import { useMutation } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { Badge, Button, Chip } from '@/components/ui';
import { activityApi, type Exercise, type NoteLine } from '@/features/activity/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { fileSize, reduceImage } from '@/lib/image';
import { num } from '@/lib/format';
import { useToast } from '@/lib/toast';

import styles from '../Activity.module.css';
import type { DraftEntry } from './NewActivitySheet';
import { useInvalidateActivity } from './shared';

/** Ce qu'une ligne devient à l'écran, une fois validée ou non. */
interface Reviewed extends NoteLine {
  /** Vrai quand la ligne peut rejoindre la séance : reconnue, ou acceptée. */
  ready: boolean;
}

/** Comment une charge lue se lit sur une ligne. */
function loadLabel(line: NoteLine): string {
  if (line.weight_kg === null) return line.note ?? 'charge non lue';
  return line.weight_kg === 0 ? 'poids du corps' : `${num(line.weight_kg, 1)} kg`;
}

export function NotesStep({
  catalogue,
  onAccepted,
  onCancel,
}: {
  catalogue: Exercise[];
  /** Les lignes prêtes, converties en exercices de la séance. */
  onAccepted: (entries: DraftEntry[]) => void;
  onCancel: () => void;
}) {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();

  const [text, setText] = useState('');
  const [photo, setPhoto] = useState<File | null>(null);
  const [weight, setWeight] = useState<number | null>(null);
  const [lines, setLines] = useState<Reviewed[] | null>(null);

  const fileInput = useRef<HTMLInputElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);

  // La zone de texte grandit avec ce qu'on y colle : six exercices dans une fente d'une
  // ligne, c'est le défaut que la saisie de l'assistant vient de perdre.
  useEffect(() => {
    const node = composer.current;
    if (node === null) return;
    node.style.height = 'auto';
    node.style.height = `${String(node.scrollHeight)}px`;
  }, [text]);

  const choose = useMutation({
    mutationFn: async (file: File | null) => (file === null ? null : reduceImage(file)),
    onSuccess: (result) => {
      setPhoto(result?.file ?? null);
      setWeight(result?.file.size ?? null);
    },
    onError: () => {
      notify('Cette image n’a pas pu être lue. Essaie une autre photo.', 'recover');
    },
  });

  const read = useMutation({
    mutationFn: () => activityApi.readNotes(text, photo),
    onSuccess: (draft) => {
      // Une ligne déjà connue est prête d'emblée : elle n'écrit rien au catalogue.
      setLines(draft.lines.map((line) => ({ ...line, ready: line.status === 'known' })));
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Lecture impossible.', 'recover');
    },
  });

  /** Accepte une ligne : crée l'exercice, ou lui ajoute la graphie de la note. */
  const accept = useMutation({
    mutationFn: async (line: Reviewed) => {
      if (line.status === 'new') {
        return activityApi.createExercise(line.name, line.muscle_group);
      }
      if (line.exercise_id === null || line.alias_of === null) {
        throw new ApiError({ code: 'validation_error', message: 'Ligne incomplète.' }, 422);
      }
      return activityApi.addAlias(line.exercise_id, line.alias_of);
    },
    onSuccess: (exercise, line) => {
      invalidate();
      setLines((current) =>
        (current ?? []).map((item) =>
          item === line
            ? {
                ...item,
                ready: true,
                status: 'known',
                exercise_id: exercise.exercise_id,
                name: exercise.name,
                muscle_group: exercise.muscle_group,
              }
            : item,
        ),
      );
      notify(
        line.status === 'new'
          ? `« ${exercise.name} » ajouté au catalogue.`
          : `« ${line.alias_of ?? ''} » sera reconnu la prochaine fois.`,
        'signal',
      );
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Impossible.', 'recover');
    },
  });

  function drop(line: Reviewed): void {
    setLines((current) => (current ?? []).filter((item) => item !== line));
  }

  // ── La saisie ───────────────────────────────────────

  if (lines === null) {
    return (
      <div className={styles.form}>
        <div className={styles.pickField}>
          <label className={styles.pickLabel} htmlFor="notes">
            Tes notes
          </label>
          <textarea
            id="notes"
            ref={composer}
            className={styles.notes}
            rows={3}
            value={text}
            placeholder="développé couché 4x8 60kg&#10;tractions 3xmax&#10;curl haltères 3x12 12kg"
            onChange={(event) => {
              setText(event.target.value);
            }}
          />
        </div>

        <input
          ref={fileInput}
          id="notes-photo"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          capture="environment"
          className="sr-only"
          onChange={(event) => {
            choose.mutate(event.target.files?.[0] ?? null);
          }}
        />
        <label htmlFor="notes-photo" className={styles.drop}>
          {choose.isPending
            ? 'réduction…'
            : photo === null
              ? 'ou photographier le carnet'
              : `photo prête${weight === null ? '' : ` — ${fileSize(weight)}`}`}
        </label>

        <div className={styles.sheetCommit}>
          <Button
            variant="primary"
            className={styles.commit}
            busy={read.isPending}
            disabled={text.trim() === '' && photo === null}
            onClick={() => {
              read.mutate();
            }}
          >
            Lire
          </Button>
          <Button variant="quiet" disabled={read.isPending} onClick={onCancel}>
            Retour
          </Button>
        </div>

        <p className={styles.empty}>
          Rien n’est enregistré : la lecture produit un tableau que tu valides ligne par ligne.
        </p>
      </div>
    );
  }

  // ── Le tableau ──────────────────────────────────────

  const ready = lines.filter((line) => line.ready);
  const pending = lines.length - ready.length;

  return (
    <div className={styles.form}>
      <p className={styles.note}>
        {lines.length} {lines.length > 1 ? 'exercices lus' : 'exercice lu'}
        {pending > 0 && ` · ${String(pending)} à valider avant de les ajouter`}
      </p>

      <div className={styles.entries}>
        {lines.map((line, position) => (
          <div
            className={cx(styles.noteRow, !line.ready && styles.noteRowPending)}
            key={`${line.name}-${String(position)}`}
          >
            <div className={styles.noteBody}>
              <span className={styles.noteName}>
                {line.name} <Badge tone="signal">{line.muscle_group}</Badge>
                {line.status === 'alias' && <Badge tone="load">à rapprocher</Badge>}
                {line.status === 'new' && <Badge tone="load">à créer</Badge>}
              </span>
              <span className={styles.entryDetail}>
                {line.sets ?? '—'}×{line.reps ?? '—'} · {loadLabel(line)}
              </span>
              {/* Ce que la validation coûterait, dit **avant** le geste. Le projet n'a
                  pas d'annulation, et une fusion erronée pollue l'historique. */}
              {line.status === 'alias' && (
                <span className={styles.entryDetail}>
                  « {line.alias_of} » deviendrait une autre écriture de « {line.name} »
                </span>
              )}
              {line.status === 'new' && (
                <span className={styles.entryDetail}>
                  créerait une entrée au catalogue, groupe « {line.muscle_group} »
                </span>
              )}
            </div>

            <div className={styles.catalogueActions}>
              {!line.ready && (
                <Chip
                  disabled={accept.isPending}
                  aria-label={
                    line.status === 'new'
                      ? `Créer ${line.name} au catalogue`
                      : `Rapprocher ${line.alias_of ?? ''} de ${line.name}`
                  }
                  onClick={() => {
                    accept.mutate(line);
                  }}
                >
                  {line.status === 'new' ? 'Créer' : 'Rapprocher'}
                </Chip>
              )}
              <Chip
                aria-label={`Retirer ${line.name} du tableau`}
                onClick={() => {
                  drop(line);
                }}
              >
                Retirer
              </Chip>
            </div>
          </div>
        ))}
      </div>

      <div className={styles.sheetCommit}>
        <Button
          variant="primary"
          className={styles.commit}
          disabled={ready.length === 0}
          onClick={() => {
            onAccepted(
              ready.map((line) => ({
                exercise_id: line.exercise_id ?? '',
                name: line.name,
                muscle_group: line.muscle_group,
                // La charge repart en **texte**, comme toute saisie : le serveur la relit
                // (`ACT-01`). Une charge non lue part vide et se complète au formulaire.
                weight_kg: line.weight_kg === null ? '' : String(line.weight_kg),
                sets: line.sets ?? 1,
                reps: line.reps ?? 1,
              })),
            );
          }}
        >
          {ready.length === 0
            ? 'Valide au moins une ligne'
            : `Ajouter ${String(ready.length)} ${ready.length > 1 ? 'exercices' : 'exercice'}`}
        </Button>
        <Button
          variant="quiet"
          onClick={() => {
            setLines(null);
          }}
        >
          Retour
        </Button>
      </div>

      {/* Abandonner après avoir vu le tableau ne doit rien laisser derrière soi — sauf ce
          qu'on a explicitement accepté, qui est déjà au catalogue et le reste. */}
      <p className={styles.empty}>
        {catalogue.length === 0
          ? 'Le catalogue est vide : tout arrive en création.'
          : 'Les lignes retirées ne sont pas enregistrées.'}
      </p>
    </div>
  );
}
