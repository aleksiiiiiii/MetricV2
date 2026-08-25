/**
 * Le journal de séance — le parcours principal de l'écran, et il est **en tête**.
 *
 * Il était en quatrième position, sous quatre sections de statistiques : consigner une
 * série entre deux exercices demandait de traverser l'écran. L'ordre affiché contredisait
 * l'ordre du geste. Les statistiques n'ont pas disparu, elles ont reculé — on ouvre
 * `/activite` avec le téléphone dans une main, pas pour lire un tonnage hebdomadaire.
 *
 * **Le formulaire est au-dessus de la liste**, et c'est la seconde inversion. À la
 * huitième série de la séance, une liste au-dessus aurait poussé le formulaire de ~400 px
 * vers le bas — précisément au moment où l'on s'en sert le plus. Sa place ne dépend plus
 * du nombre de fois qu'on l'a déjà employé.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import {
  Badge,
  Button,
  Card,
  CardHead,
  Chip,
  ChipStrip,
  Empty,
  Field,
  LinkButton,
  LogButton,
  Stepper,
  SwipeRow,
} from '@/components/ui';
import {
  activityApi,
  type Exercise,
  type ExerciseEntry,
  type ExerciseEntryPayload,
} from '@/features/activity/api';
import { ApiError } from '@/lib/api';
import { celebrate } from '@/lib/confetti';
import { cx } from '@/lib/cx';
import { hoursMinutes, num, plural, shortDate } from '@/lib/format';
import { keys } from '@/lib/query';
import { useHorizontalSwipe } from '@/lib/swipe';
import { useToast } from '@/lib/toast';

import styles from '../Activity.module.css';
import { fold, kgText, useInvalidateActivity, type Session } from './shared';

/** Exercices proposés d'emblée, avant toute recherche. */
const SUGGESTED = 6;

/** Résultats affichés au plus pour une recherche. Au-delà, préciser coûte moins que défiler. */
const MATCHES = 8;

/** Comment une série se lit sur une ligne, et dans un nom accessible. */
function seriesLabel(entry: ExerciseEntry): string {
  const load = entry.weight_kg === 0 ? 'poids du corps' : `${num(entry.weight_kg, 1)} kg`;
  return `${entry.exercise_name}, ${load}, ${String(entry.sets)}×${String(entry.reps)}`;
}

// ── Le formulaire de série ────────────────────────────

/**
 * Consigner une série, ou en corriger une.
 *
 * Le même formulaire pour les deux, comme sur `/corps` : un second formulaire de
 * correction divergerait du premier au premier champ ajouté. L'appelant le remonte par
 * une `key` quand la ligne corrigée change, ce qui remet les champs à leur valeur de
 * départ sans effet de bord.
 */
function SeriesForm({
  workoutId,
  catalogue,
  editing,
  onDone,
}: {
  workoutId: number;
  catalogue: Exercise[] | undefined;
  editing: ExerciseEntry | null;
  onDone: () => void;
}) {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();

  // Même clé que l'écran : la requête est mutualisée, pas dupliquée.
  const { data: progress } = useQuery({
    queryKey: keys.activity.progress(),
    queryFn: activityApi.progress,
  });

  // Séries et réps restent du **texte** tant qu'on saisit : les convertir à chaque frappe
  // ramenait le champ à 1 dès qu'on l'effaçait pour retaper.
  const [form, setForm] = useState({
    exercise_id: editing?.exercise_id ?? '',
    weight_kg: editing === null ? '' : kgText(editing.weight_kg),
    sets: editing === null ? '3' : String(editing.sets),
    reps: editing === null ? '8' : String(editing.reps),
  });
  const [query, setQuery] = useState('');
  const [error, setError] = useState<ApiError | null>(null);

  // Le formulaire est au-dessus de la liste, et le sélecteur d'exercice le rend haut :
  // à la douzième série, appuyer sur une ligne pour la corriger ne montrerait rien. On
  // amène **les chiffres et le bouton** sous les yeux, pas le haut du formulaire — c'est
  // là que la correction se décide. Au montage : l'appelant remonte par une `key`.
  const commitRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (editing === null) return;
    commitRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
  }, [editing]);

  const set = (name: keyof typeof form) => (value: string) => {
    setForm((current) => ({ ...current, [name]: value }));
  };

  const save = useMutation({
    mutationFn: () => {
      const payload: ExerciseEntryPayload = {
        exercise_id: form.exercise_id,
        weight_kg: form.weight_kg,
        sets: Number(form.sets.replace(',', '.')) || 1,
        reps: Number(form.reps.replace(',', '.')) || 1,
      };
      return editing === null
        ? activityApi.logExercise(workoutId, payload)
        : activityApi.updateEntry(editing.id, editing.token, payload);
    },
    onSuccess: () => {
      invalidate();
      // La fête à l'**ajout** seulement : corriger une série est un rattrapage, pas un
      // accomplissement, et célébrer les deux reviendrait à ne célébrer ni l'un ni l'autre.
      if (editing === null) celebrate();
      notify(editing === null ? 'Performance consignée.' : 'Série corrigée.', 'effort');
      setForm((current) => ({ ...current, weight_kg: '' }));
      setError(null);
      onDone();
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
      if (caught instanceof ApiError && caught.code === 'conflict') invalidate();
    },
  });

  const entries = catalogue ?? [];
  const empty = catalogue !== undefined && entries.length === 0;
  const selected = entries.find((item) => item.exercise_id === form.exercise_id);

  /*
   * La recherche a remplacé la grille.
   *
   * Le sélecteur affichait **tout le catalogue**, un bouton par exercice. À vingt-cinq
   * exercices cela faisait treize rangées et plus d'une hauteur d'écran, au-dessus des
   * champs qu'on vient remplir — et le filtre par groupe musculaire, neuf pastilles de
   * plus, s'ajoutait par-dessus pour rattraper le problème qu'il créait.
   *
   * Un champ, et la liste se réduit à ce qu'on cherche. La recherche porte aussi sur le
   * **groupe musculaire** : taper « dos » rend les exercices de dos, ce qui absorbe le
   * filtre à pastilles au lieu de le doubler.
   *
   * Filtrer et ordonner ne sont pas dériver : ce sont les lignes du serveur, dans un
   * autre ordre. Aucun nombre n'est calculé ici.
   */
  const asked = fold(query.trim());
  const matched =
    asked === ''
      ? [...entries]
          // Sans recherche, ce qu'on a soulevé le plus récemment : la date vient du
          // serveur, on ne fait que s'en servir pour ranger.
          .sort((a, b) => (b.last_date ?? '').localeCompare(a.last_date ?? ''))
      : entries.filter(
          (item) => fold(item.name).includes(asked) || fold(item.muscle_group).includes(asked),
        );

  // Le plafond s'applique **après** le compte, jamais avant. En coupant `matched` d'abord,
  // le reste valait toujours zéro : sept exercices au catalogue, six à l'écran, et rien
  // qui dise qu'il en manquait un. Vu en capture, pas par un test.
  const shown = matched.slice(0, asked === '' ? SUGGESTED : MATCHES);
  const hidden = matched.length - shown.length;

  // L'exercice choisi reste visible même quand la recherche ne le rend plus : sans cela,
  // taper une lettre de trop effaçait de l'écran ce sur quoi la charge va être consignée.
  const list =
    selected !== undefined && !shown.some((item) => item.exercise_id === selected.exercise_id)
      ? [selected, ...shown]
      : shown;

  // Charges rapides : les dernières valeurs **réellement soulevées**, telles que le
  // serveur les a calculées (`max_series`). Aucune n'est suggérée par arrondi ni par
  // progression supposée — une pastille propose ce qui a existé, pas ce qui devrait.
  const history = progress?.find((item) => item.exercise_id === form.exercise_id);
  const quick = [...new Set(history?.max_series ?? [])].slice(-3).reverse();

  /**
   * Choisir un exercice reprend ses séries et ses réps de la dernière fois.
   *
   * Ce sont des valeurs **mesurées**, pas devinées : le catalogue les rend (`ACT-08`), et
   * elles remplacent le `3×8` qui était écrit en dur — lui, personne ne l'avait jamais
   * soulevé. La charge, elle, reste vide : c'est elle qui progresse, c'est le seul nombre
   * qui vaut d'être tapé, et les pastilles ci-dessous la remplissent en un appui.
   *
   * Sans le trait discontinu du pas-à-pas : `proposed` veut dire « un modèle a suggéré
   * ceci », et le projet n'a qu'une façon de le dire. Un relevé rappelé n'en est pas une.
   */
  function pick(item: Exercise): void {
    setForm((current) => ({
      ...current,
      exercise_id: item.exercise_id,
      sets: item.last_sets == null ? current.sets : String(item.last_sets),
      reps: item.last_reps == null ? current.reps : String(item.last_reps),
    }));
  }

  return (
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

      {/* Sélection par recherche : un champ, puis un appui par exercice avec sa dernière
          charge en regard. La liste déroulante native demandait un appui, un panneau
          système, un défilement et un second appui — pour le geste le plus répété de
          l'écran ; la grille complète, elle, prenait la hauteur de l'écran. */}
      <div className={styles.pickField}>
        {empty ? (
          <>
            <span className={styles.pickLabel}>Exercice</span>
            <span className={styles.empty}>
              catalogue vide — déclare un exercice pour pouvoir consigner une charge
            </span>
          </>
        ) : (
          <>
            <Field
              label="Exercice"
              type="search"
              // `search` et non `text` : iOS rend une croix d'effacement native, et un
              // clavier dont la touche d'action dit « rechercher ».
              placeholder="nom ou groupe musculaire…"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
              }}
            />

            <div className={styles.pickList} role="group" aria-label="Exercices proposés">
              {list.map((item) => (
                <LogButton
                  key={item.exercise_id}
                  label={item.name}
                  // « 0 kg » se lirait comme une mesure manquante. Le reste de l'écran
                  // dit « poids du corps » ; il n'y a pas de raison d'un second mot ici.
                  hint={
                    item.last_weight_kg == null
                      ? item.muscle_group
                      : item.last_weight_kg === 0
                        ? 'poids du corps'
                        : `${num(item.last_weight_kg, 1)} kg`
                  }
                  aria-pressed={form.exercise_id === item.exercise_id}
                  className={cx(form.exercise_id === item.exercise_id && styles.pickOn)}
                  onClick={() => {
                    pick(item);
                  }}
                />
              ))}
            </div>

            {/* Ce que la liste ne montre pas se dit, plutôt que de laisser croire que le
                catalogue s'arrête là. Et un catalogue vide de résultats n'est pas un
                catalogue vide : les deux phrases sont différentes. */}
            {list.length === 0 ? (
              <span className={styles.empty}>
                aucun exercice ne correspond — vérifie l’orthographe, ou déclare-le
              </span>
            ) : (
              hidden > 0 && (
                <span className={styles.empty}>
                  {hidden} {plural(hidden, 'autre')} au catalogue
                  {asked === '' ? ' — cherche par nom ou groupe' : ' — précise ta recherche'}
                </span>
              )
            )}
          </>
        )}

        {/* Découvrir un exercice manquant en pleine séance demandait de descendre tout
            l'écran, de le déclarer, de remonter et de le re-choisir. C'est maintenant
            une navigation vers le catalogue, et le bouton système « précédent » ramène
            ici — la séance ouverte et les champs déjà tapés sont intacts. */}
        <div className={styles.missing}>
          <LinkButton to="/activite/catalogue">Déclarer un exercice</LinkButton>
        </div>
      </div>

      {/* `ACT-08` : choisir sa charge sans consulter l'historique. */}
      {selected?.last_weight_kg != null && (
        <span className={styles.empty}>
          dernière fois : {num(selected.last_weight_kg, 1)} kg · {selected.last_sets}×
          {selected.last_reps}
        </span>
      )}

      {quick.length > 0 && (
        <ChipStrip label="Charges récentes">
          {quick.map((weight) => (
            <Chip
              key={weight}
              selected={form.weight_kg === kgText(weight)}
              onClick={() => {
                set('weight_kg')(kgText(weight));
              }}
            >
              {num(weight, 1)} kg
            </Chip>
          ))}
        </ChipStrip>
      )}

      {/* Ce que la correction remplace, juste au-dessus des chiffres qui la remplacent
          et du bouton qui l'envoie : sans annulation, c'est le dernier endroit où une
          erreur de ligne peut encore se voir. En tête du formulaire, elle était hors de
          l'écran au moment de l'appui. */}
      {editing !== null && (
        <p className={styles.wasValue}>
          <Badge tone="load">correction</Badge> était : {seriesLabel(editing)}
        </p>
      )}

      <div className={styles.logGrid} ref={commitRef}>
        <Stepper
          label="Charge (kg)"
          value={form.weight_kg}
          onChange={set('weight_kg')}
          // 2,5 kg est le plus petit disque de la plupart des salles : c'est le pas
          // réel d'une progression, pas un pas décidé à la calculette.
          step={2.5}
          min={0}
          placeholder="0 = poids du corps"
          error={error?.messageFor('weight_kg')}
        />
        <Stepper
          label="Séries"
          inputMode="numeric"
          value={form.sets}
          onChange={set('sets')}
          min={1}
          max={20}
        />
        <Stepper
          label="Réps"
          inputMode="numeric"
          value={form.reps}
          onChange={set('reps')}
          min={1}
          max={50}
        />
      </div>

      <div className={styles.sheetCommit}>
        <Button
          type="submit"
          variant="primary"
          className={styles.commit}
          busy={save.isPending}
          disabled={form.exercise_id === ''}
        >
          {editing === null ? 'Consigner' : 'Corriger la série'}
        </Button>
        {editing !== null && (
          <Button variant="quiet" onClick={onDone}>
            Annuler
          </Button>
        )}
      </div>
    </form>
  );
}

// ── Le contenu d'une séance ───────────────────────────

/** Ce qui est déjà consigné, et de quoi consigner la suite. */
function SessionLog({
  workoutId,
  onEditWorkout,
}: {
  workoutId: number;
  onEditWorkout: () => void;
}) {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const { data: catalogue } = useQuery({
    queryKey: keys.activity.exercises(),
    queryFn: activityApi.exercises,
  });

  // La séance est relue **ici**. Un refus du serveur s'affiche donc à la place du
  // journal, là où le regard est déjà : porté par un toast depuis le bouton « ouvrir »,
  // il passait avant d'avoir été lu — quand il n'était pas simplement avalé.
  const {
    data: detail,
    isPending,
    error: unreadable,
  } = useQuery({
    queryKey: keys.activity.workout(workoutId),
    queryFn: () => activityApi.readWorkout(workoutId),
  });

  const [editing, setEditing] = useState<ExerciseEntry | null>(null);

  const remove = useMutation({
    mutationFn: (entry: ExerciseEntry) => activityApi.deleteEntry(entry.id, entry.token),
    onSuccess: (_removed, entry) => {
      // Le formulaire ne doit pas rester braqué sur une série qui n'existe plus.
      if (editing?.id === entry.id) setEditing(null);
      invalidate();
      notify('Série supprimée.', 'signal');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Suppression impossible.', 'recover');
      invalidate();
    },
  });

  if (unreadable !== null) {
    return (
      <p className={cx(styles.error, styles.spaced)} role="alert">
        {unreadable instanceof ApiError ? unreadable.message : 'Séance illisible.'}
      </p>
    );
  }

  if (isPending) {
    return <p className={cx(styles.empty, styles.spaced)}>chargement…</p>;
  }

  // Une réponse partielle ne doit pas produire un écran blanc.
  const entries = detail.exercises ?? [];

  return (
    <>
      <div className={styles.meta}>
        {/* **La date est revenue ici.** Elle était omise parce que la bande de pastilles
            juste au-dessus la portait déjà ; cette bande a disparu, et sans elle plus
            rien ne disait dans quelle séance la charge allait s'écrire. C'est la seule
            information de cette ligne dont une erreur coûte une donnée fausse. */}
        <p className={styles.note}>
          <strong>{shortDate(detail.date)}</strong> · {detail.type} ·{' '}
          {hoursMinutes(detail.duration_min)}
          {detail.volume_kg > 0 && ` · ${num(detail.volume_kg, 0)} kg de tonnage`}
        </p>
        {detail.rpe !== null && <Badge tone="load">RPE {detail.rpe}</Badge>}
        <Chip
          aria-label={`Corriger la séance du ${shortDate(detail.date)}`}
          onClick={onEditWorkout}
        >
          corriger la séance
        </Chip>
      </div>

      <SeriesForm
        key={editing?.token ?? 'new'}
        workoutId={workoutId}
        catalogue={catalogue}
        editing={editing}
        onDone={() => {
          setEditing(null);
        }}
      />

      {entries.length > 0 && (
        <div className={styles.entries}>
          <p className={styles.pickLabel}>
            Déjà consigné · {entries.length} {plural(entries.length, 'série')}
          </p>

          {entries.map((item) => (
            <SwipeRow
              key={`${String(item.id)}-${item.token}`}
              actionLabel={`Supprimer la série — ${seriesLabel(item)}`}
              busy={remove.isPending}
              onAction={() => {
                remove.mutate(item);
              }}
            >
              {/* La ligne entière corrige : c'est la cible la plus large possible, et
                  le glissement garde la suppression pour lui. */}
              <button
                type="button"
                className={cx(styles.entry, editing?.id === item.id && styles.entryOn)}
                aria-label={`Corriger la série — ${seriesLabel(item)}`}
                onClick={() => {
                  setEditing(item);
                }}
              >
                <span>
                  {item.exercise_name}
                  <span className={styles.entryDetail}> · {item.muscle_group}</span>
                </span>
                <span className={styles.entryDetail}>
                  {item.weight_kg === 0 ? 'poids du corps' : `${num(item.weight_kg, 1)} kg`} ·{' '}
                  {item.sets}×{item.reps}
                  {item.one_rep_max_kg !== null && ` · 1RM ${num(item.one_rep_max_kg, 0)}`}
                </span>
              </button>
            </SwipeRow>
          ))}
        </div>
      )}
    </>
  );
}

// ── Le journal ────────────────────────────────────────

export function Journal({
  sessions,
  currentId,
  onPick,
  onNew,
  onEditWorkout,
  ready,
}: {
  sessions: Session[];
  currentId: number | null;
  onPick: (session: Session) => void;
  /** Ouvre l'assistant de création. Il demande lui-même de quoi il s'agit. */
  onNew: () => void;
  onEditWorkout: (id: number) => void;
  /** Le jour du serveur est connu. Sans lui, une saisie ne peut pas se dater. */
  ready: boolean;
}) {
  // Balayer le journal passe d'une séance à l'autre — vers la gauche on remonte le temps,
  // vers la droite on revient au récent. C'est un raccourci, jamais la seule porte :
  // l'historique, juste dessous, porte un « ouvrir » par séance et il est dans le
  // document. La date affichée sous le titre dit à chaque instant où l'on a atterri.
  const rank = sessions.findIndex((item) => item.id === currentId);
  const swipe = useHorizontalSwipe({
    touchOnly: true,
    onLeft: () => {
      const older = sessions[rank + 1];
      if (older !== undefined) onPick(older);
    },
    onRight: () => {
      const newer = sessions[rank - 1];
      if (newer !== undefined) onPick(newer);
    },
  });

  return (
    <Card>
      <CardHead>
        <div>
          <h3>Journal de séance</h3>
          {/* La promesse ne vaut que s'il y a une séance à ouvrir : l'annoncer quand il
              n'y en a aucune décrirait un écran que l'utilisateur n'a pas sous les yeux. */}
          <p className={styles.note}>
            Les charges se consignent ici.
            {currentId !== null && ' La séance la plus récente est ouverte d’office.'}
          </p>
        </div>
        {/* **Une seule porte.** Il y en avait deux — « Nouvelle séance » et « Nouvelle
            course » —, ce qui demandait de trancher avant d'avoir ouvert quoi que ce
            soit, et laissait deux cibles côte à côte dans un en-tête de 390 px. C'est
            désormais la première étape de l'assistant, où la question a la place de se
            poser en toutes lettres. */}
        <div className={styles.headActions}>
          <Button variant="primary" disabled={!ready} onClick={onNew}>
            Enregistrer une activité
          </Button>
        </div>
      </CardHead>

      {currentId === null ? (
        <div className={styles.spaced}>
          <Empty title="Aucune séance">
            Enregistre une séance — sa date et sa durée suffisent. Ses exercices et leurs charges se
            consignent ensuite ici, un par un.
          </Empty>
        </div>
      ) : (
        /* Remonter le journal à chaque changement de séance : une charge tapée pour
           l'une ne doit pas se retrouver pré-remplie sur l'autre. */
        <div className={styles.swipeArea} {...swipe.handlers}>
          <SessionLog
            key={currentId}
            workoutId={currentId}
            onEditWorkout={() => {
              onEditWorkout(currentId);
            }}
          />
        </div>
      )}
    </Card>
  );
}
