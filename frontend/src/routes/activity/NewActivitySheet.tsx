/**
 * Enregistrer une activité — un assistant, une étape par écran (`C06`).
 *
 * La feuille demandait tout d'un coup : nature, date, durée, type, effort, note, dans un
 * seul formulaire qu'il fallait parcourir en entier avant de savoir ce qui était
 * obligatoire. Elle demande maintenant **une chose à la fois**, et ce qu'elle demande
 * dépend de la première réponse.
 *
 * ```
 * étape 0   Course ou Séance ?
 *
 * Séance    1. date, durée, effort perçu          → Suivant
 *           2. les exercices, par la recherche    → Enregistrer
 *
 * Course    1. la capture, ou rien                → Suivant
 *           2. temps, allure, distance, cadence   → Enregistrer
 * ```
 *
 * ## Trois décisions
 *
 * **Rien n'est écrit avant le dernier appui.** La séance et ses exercices partent en un
 * seul appel — c'est ce que le backend accepte depuis ce lot. Abandonner à l'étape 2 ne
 * laisse donc aucune séance vide dans l'historique, ce qui était le prix de l'autre
 * découpage.
 *
 * **La charge d'un exercice se saisit en place, pas dans une seconde popup.** Le ticket
 * décrit « une popup demande poids, répétitions, séries » ; deux surfaces modales
 * empilées sur un téléphone de 360 px sont une impasse — on ne sait plus laquelle se
 * ferme, et la seconde recouvre la première. La ligne choisie **se déplie** à sa place et
 * porte les trois pas-à-pas. Le geste est le même, sans la pile.
 *
 * **Corriger une activité n'est pas un assistant.** Reprendre une séance déjà écrite
 * garde le formulaire d'un seul tenant : on vient changer un champ, pas dérouler un
 * parcours. C'est `ActivitySheet` qui s'en charge, inchangée.
 */

import { useMutation } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { Button, Field, Sheet, Stepper } from '@/components/ui';
import { activityApi } from '@/features/activity/api';
import { useAiStatus } from '@/features/ai/useAiStatus';
import { importsApi, type AppleDraft } from '@/features/imports/api';
import { ApiError } from '@/lib/api';
import { fileSize, reduceImage } from '@/lib/image';
import { useToast } from '@/lib/toast';

import styles from '../Activity.module.css';
import { useInvalidateActivity } from './shared';

export function NewActivitySheet({
  open,
  today,
  onClose,
}: {
  open: boolean;
  today: string;
  onClose: () => void;
}) {
  const [step, setStep] = useState(1);

  function close(): void {
    setStep(1);
    onClose();
  }

  return (
    <Sheet open={open} onClose={close} title="Course" lede={`Étape ${String(step)} sur 2`}>
      {/* **L'étape 0 a disparu avec la séance.** Elle demandait « Course ou Séance ? » ;
          il ne reste qu'une nature à saisir à la main, et poser une question dont la
          réponse est déjà connue est un appui de plus pour rien. « Retour », à la
          première étape, ferme donc la feuille au lieu de remonter à ce choix. */}
      <RunWizard today={today} step={step} onStep={setStep} onBack={close} onDone={close} />
    </Sheet>
  );
}

// ── Parcours Course ───────────────────────────────────

/** Les champs d'une course, tous en texte jusqu'au serveur (`ACT-01`). */
interface RunFields {
  date: string;
  duration_min: string;
  distance_km: string;
  pace_min_km: string;
  cadence_spm: string;
  avg_hr: string;
  note: string;
}

function RunWizard({
  today,
  step,
  onStep,
  onBack,
  onDone,
}: {
  today: string;
  step: number;
  onStep: (step: number) => void;
  onBack: () => void;
  onDone: () => void;
}) {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const ai = useAiStatus();

  const [fields, setFields] = useState<RunFields>({
    date: today,
    duration_min: '',
    distance_km: '',
    pace_min_km: '',
    cadence_spm: '',
    avg_hr: '',
    note: '',
  });
  /** Ce qui vient de la capture et n'a pas encore été retouché (`IMP-02`). */
  const [proposed, setProposed] = useState<string[]>([]);
  /**
   * Le dernier des deux champs liés qu'on a touché.
   *
   * Distance et allure sont deux lectures du même trajet, et le **serveur** calcule l'une
   * depuis l'autre. Quand les deux sont remplies, il faut lui dire laquelle défendre :
   * c'est celle qu'on vient de corriger. Sans ce choix, l'écran enverrait les deux et la
   * règle du serveur trancherait à l'aveugle.
   */
  const [edited, setEdited] = useState<'distance' | 'pace' | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const save = useMutation({
    mutationFn: () =>
      activityApi.createRun({
        date: fields.date,
        duration_min: fields.duration_min,
        // On n'envoie que celui qu'on défend, quand les deux sont là.
        distance_km: edited === 'pace' ? null : fields.distance_km || null,
        pace_min_km: edited === 'distance' ? null : fields.pace_min_km || null,
        cadence_spm: fields.cadence_spm || null,
        avg_hr: fields.avg_hr || null,
        note: fields.note || null,
      }),
    onSuccess: () => {
      invalidate();
      notify('Course enregistrée.', 'effort');
      onDone();
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
    },
  });

  const set = (name: keyof RunFields) => (value: string) => {
    setFields((current) => ({ ...current, [name]: value }));
    // Corriger une valeur proposée la fait sienne : la marque disparaît.
    setProposed((current) => current.filter((field) => field !== name));
    if (name === 'distance_km') setEdited('distance');
    if (name === 'pace_min_km') setEdited('pace');
  };

  if (step === 1) {
    return (
      <AppleStep
        today={today}
        enabled={ai.enabled}
        onSkip={() => {
          onStep(2);
        }}
        onBack={onBack}
        onRead={(draft) => {
          setFields((current) => ({
            ...current,
            date: draft.date ?? current.date,
            duration_min: draft.duration_min == null ? '' : String(draft.duration_min),
            distance_km: draft.distance_km == null ? '' : String(draft.distance_km),
            pace_min_km: draft.pace_min_km == null ? '' : String(draft.pace_min_km),
            cadence_spm: draft.cadence_spm == null ? '' : String(draft.cadence_spm),
            avg_hr: draft.avg_hr == null ? '' : String(draft.avg_hr),
          }));
          setProposed(
            (
              [
                'date',
                'duration_min',
                'distance_km',
                'pace_min_km',
                'cadence_spm',
                'avg_hr',
              ] as const
            )
              .filter((field) => !draft.missing.includes(field))
              .map(String),
          );
          setEdited(null);
          onStep(2);
        }}
      />
    );
  }

  return (
    <div className={styles.form}>
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
          onChange={(event) => {
            set('date')(event.target.value);
          }}
        />
        <Field
          label="Temps"
          placeholder="44:12 ou 1h30"
          hint="mm:ss, h:mm:ss ou minutes"
          value={fields.duration_min}
          error={error?.messageFor('duration_min')}
          onChange={(event) => {
            set('duration_min')(event.target.value);
          }}
        />
      </div>

      {/* Distance **et** allure sont modifiables, et le serveur recalcule celle qu'on n'a
          pas touchée. C'est pour cela qu'elles sont côte à côte : leur lien se voit. */}
      <div className={styles.pair}>
        <Stepper
          label="Distance (km)"
          value={fields.distance_km}
          onChange={set('distance_km')}
          step={0.5}
          min={0}
          proposed={proposed.includes('distance_km')}
          error={error?.messageFor('distance_km')}
        />
        <Field
          label="Allure (min/km)"
          placeholder="5:16"
          hint={
            edited === 'pace'
              ? 'la distance sera recalculée'
              : edited === 'distance'
                ? 'l’allure sera recalculée'
                : 'l’une des deux suffit'
          }
          value={fields.pace_min_km}
          error={error?.messageFor('pace_min_km')}
          onChange={(event) => {
            set('pace_min_km')(event.target.value);
          }}
        />
      </div>

      <div className={styles.logGrid}>
        <Stepper
          label="Cadence (SPM)"
          inputMode="numeric"
          value={fields.cadence_spm}
          onChange={set('cadence_spm')}
          step={1}
          min={0}
          proposed={proposed.includes('cadence_spm')}
          error={error?.messageFor('cadence_spm')}
        />
        <Stepper
          label="FC moyenne"
          inputMode="numeric"
          value={fields.avg_hr}
          onChange={set('avg_hr')}
          step={5}
          min={0}
          proposed={proposed.includes('avg_hr')}
          error={error?.messageFor('avg_hr')}
        />
      </div>

      <Field
        label="Ressenti"
        placeholder="jambes lourdes, vent de face…"
        value={fields.note}
        onChange={(event) => {
          setFields((current) => ({ ...current, note: event.target.value }));
        }}
      />

      <div className={styles.sheetCommit}>
        <Button
          variant="primary"
          className={styles.commit}
          busy={save.isPending}
          disabled={
            fields.duration_min === '' || (fields.distance_km === '' && fields.pace_min_km === '')
          }
          onClick={() => {
            save.mutate();
          }}
        >
          Enregistrer la course
        </Button>
        <Button
          variant="quiet"
          disabled={save.isPending}
          onClick={() => {
            onStep(1);
          }}
        >
          Retour
        </Button>
      </div>

      {fields.duration_min !== '' && fields.distance_km === '' && fields.pace_min_km === '' && (
        <p className={styles.empty}>
          Il manque encore la distance, ou l’allure. Le serveur calcule celle que tu ne donnes pas.
        </p>
      )}
    </div>
  );
}

// ── L'étape 1 d'une course : la capture ───────────────

function AppleStep({
  today,
  enabled,
  onRead,
  onSkip,
  onBack,
}: {
  today: string;
  enabled: boolean;
  onRead: (draft: AppleDraft) => void;
  onSkip: () => void;
  onBack: () => void;
}) {
  const { notify } = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [weight, setWeight] = useState<number | null>(null);

  useEffect(() => {
    if (preview === null) return;
    return () => {
      URL.revokeObjectURL(preview);
    };
  }, [preview]);

  const choose = useMutation({
    mutationFn: async (chosen: File | null) => (chosen === null ? null : reduceImage(chosen)),
    onSuccess: (result) => {
      setPreview((current) => {
        if (current) URL.revokeObjectURL(current);
        return result ? URL.createObjectURL(result.file) : null;
      });
      setFile(result?.file ?? null);
      setWeight(result?.file.size ?? null);
    },
    onError: () => {
      notify('Cette image n’a pas pu être lue. Essaie une autre capture.', 'recover');
    },
  });

  const read = useMutation({
    // Une seule capture ici : cette étape lit un résumé pour pré-remplir une saisie, et
    // n'a pas de tableau de paliers à recoller. L'import de `/activite` en accepte deux.
    mutationFn: (screenshot: File) => importsApi.analyze([screenshot]),
    onSuccess: onRead,
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Lecture impossible.', 'recover');
    },
  });

  return (
    <div className={styles.form}>
      <p className={styles.note}>
        {enabled
          ? 'Une capture d’Apple Fitness ou de la montre suffit : elle est lue, jamais enregistrée telle quelle. Tout reste modifiable ensuite.'
          : 'La lecture de capture demande une clé OpenRouter. La saisie à la main reste entière.'}
      </p>

      {enabled && (
        <>
          <input
            ref={fileInput}
            id="apple-screenshot"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            onChange={(event) => {
              choose.mutate(event.target.files?.[0] ?? null);
            }}
          />
          {preview !== null ? (
            <img className={styles.shot} src={preview} alt="Aperçu de la capture" />
          ) : (
            <label htmlFor="apple-screenshot" className={styles.drop}>
              {choose.isPending ? 'réduction…' : 'choisir une capture d’écran'}
            </label>
          )}
          {weight !== null && (
            <span className={styles.empty}>{fileSize(weight)} — réduite avant l’envoi</span>
          )}
        </>
      )}

      <div className={styles.sheetCommit}>
        {enabled && file !== null ? (
          <Button
            variant="primary"
            className={styles.commit}
            busy={read.isPending}
            onClick={() => {
              read.mutate(file);
            }}
          >
            Lire la capture
          </Button>
        ) : (
          <Button variant="primary" className={styles.commit} onClick={onSkip}>
            Saisir à la main
          </Button>
        )}
        <Button variant="quiet" onClick={onBack}>
          Retour
        </Button>
      </div>

      {enabled && file !== null && (
        <Button variant="quiet" onClick={onSkip}>
          Passer, et saisir à la main
        </Button>
      )}

      <p className={styles.empty}>Aujourd’hui : {today}</p>
    </div>
  );
}
