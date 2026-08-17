import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { Button, Card, Empty, Field, Rule } from '@/components/ui';
import { assistantApi, type ProfilePayload, type ProfileView } from '@/features/assistant/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from './Profile.module.css';

/**
 * « Ce que je suis » (`IA-10` a contrario) — une section de `/reglages`.
 *
 * ── Pourquoi ces champs se saisissent, et ne se devinent pas ──────────────
 *
 * L'assistant remplit son carnet **tout seul** : `IA-10` l'y autorise parce qu'une note
 * fausse ne casse aucun chiffre — elle change ce qu'il croit savoir, et cela se lit et se
 * corrige. Le profil ne suit pas cette règle. Une taille fausse change toutes les charges
 * qu'on en déduit ; un jour d'entraînement inventé change tout le planning proposé. Rien
 * ici ne vient du modèle, et aucune action de son catalogue n'y touche.
 *
 * ── Aucun défaut, et c'est la différence avec les objectifs juste au-dessus ─
 *
 * Un poids cible non réglé retombe sur une valeur de repli, parce qu'un objectif doit
 * exister pour qu'un écran ait quelque chose à montrer. Une taille non saisie n'a pas de
 * repli : afficher « 175 cm » parce que c'est courant serait une valeur inventée, et le
 * modèle en déduirait des charges. Un champ vide reste vide, et la ligne correspondante ne
 * part **pas** dans la consigne.
 *
 * ── Ce qui part est montré ────────────────────────────────────────────────
 *
 * Les lignes envoyées au modèle sont affichées telles quelles, comme le condensé l'est
 * sous une réponse. C'est ce qui rend la promesse vérifiable à l'écran au lieu de la
 * laisser déclarative dans un commentaire.
 */

/*
 * Les exemples sont des `placeholder` et non des `hint`, et ça s'est vu en capture : un
 * indice s'affiche **toujours**, si bien qu'un champ contenant « lundi, mercredi, samedi »
 * était suivi de la mention « lundi, mercredi, samedi ». Un exemple n'a de sens que tant
 * que le champ est vide, ce qui est exactement la définition d'un placeholder. L'étiquette
 * reste séparée et explicite — le placeholder n'en tient jamais lieu.
 */

/** Ce que le formulaire tient. Des chaînes, y compris pour les nombres : un champ en cours
 *  de saisie passe par « 17 » avant « 178 », et un état numérique l'arrondirait en route. */
interface Draft {
  height_cm: string;
  birth_year: string;
  training_days: string;
  equipment: string;
  preferences: string;
}

function toDraft(view: ProfileView): Draft {
  return {
    height_cm: view.height_cm === null ? '' : String(view.height_cm),
    birth_year: view.birth_year === null ? '' : String(view.birth_year),
    training_days: view.training_days,
    equipment: view.equipment,
    preferences: view.preferences,
  };
}

/** Un entier saisi, ou `null`. La chaîne vide **est** l'effacement, pas une erreur. */
function whole(raw: string): number | null {
  const cleaned = raw.trim();
  if (cleaned === '') return null;
  const value = Number(cleaned);
  return Number.isFinite(value) ? Math.round(value) : null;
}

function toPayload(draft: Draft): ProfilePayload {
  return {
    height_cm: whole(draft.height_cm),
    birth_year: whole(draft.birth_year),
    training_days: draft.training_days.trim(),
    equipment: draft.equipment.trim(),
    preferences: draft.preferences.trim(),
  };
}

function same(a: Draft, b: Draft): boolean {
  return (
    a.height_cm === b.height_cm &&
    a.birth_year === b.birth_year &&
    a.training_days === b.training_days &&
    a.equipment === b.equipment &&
    a.preferences === b.preferences
  );
}

export function Profile() {
  const client = useQueryClient();
  const { notify } = useToast();

  const { data, isPending, error } = useQuery({
    queryKey: keys.assistant.profile(),
    queryFn: assistantApi.profile,
  });

  const [draft, setDraft] = useState<Draft | null>(null);

  /**
   * Le profil vit dans `settings.csv`, avec les objectifs et les créneaux de rappel.
   *
   * Sans cette invalidation croisée, la section « Objectifs » garderait un jeton périmé et
   * son prochain enregistrement partirait en `409` sans que rien ne l'explique. C'est le
   * même arrangement que la section « Rappels », et pour la même raison.
   */
  const refresh = (updated?: ProfileView) => {
    if (updated) client.setQueryData(keys.assistant.profile(), updated);
    else void client.invalidateQueries({ queryKey: keys.assistant.all() });
    void client.invalidateQueries({ queryKey: keys.settings.all() });
  };

  const save = useMutation({
    mutationFn: (view: ProfileView) =>
      assistantApi.setProfile(toPayload(draft ?? toDraft(view)), view.token),
    onSuccess: (updated) => {
      refresh(updated);
      setDraft(null);
      notify('Profil enregistré.', 'effort');
    },
    onError: (caught: unknown) => {
      // Le client décide sur le **code**, jamais sur le message (`API-07`).
      if (caught instanceof ApiError && caught.code === 'conflict') {
        refresh();
        setDraft(null);
      }
      notify(caught instanceof ApiError ? caught.message : 'Enregistrement impossible.', 'recover');
    },
  });

  if (isPending) {
    return (
      <>
        <Rule>Ce que je suis</Rule>
        <Card>chargement…</Card>
      </>
    );
  }

  if (error || !data) {
    return (
      <>
        <Rule>Ce que je suis</Rule>
        <Card>
          <Empty title="Profil indisponible">
            {error instanceof Error ? error.message : 'Le serveur n’a pas répondu.'}
          </Empty>
        </Card>
      </>
    );
  }

  const fields = draft ?? toDraft(data);
  const dirty = !same(fields, toDraft(data));

  /** `Field` rend l'événement natif : on en extrait la valeur ici, comme la section
   *  « Rappels » juste au-dessous, plutôt que d'inventer une seconde convention. */
  const set = (key: keyof Draft) => (event: { target: { value: string } }) => {
    setDraft({ ...fields, [key]: event.target.value });
  };

  return (
    <>
      <Rule>Ce que je suis</Rule>

      <Card>
        <p className={styles.note}>
          Ce que l’assistant sait de toi et qui ne change pas. Il part avant les chiffres, à chaque
          question. Rien ici ne s’écrit tout seul — contrairement au carnet, une taille fausse
          changerait toutes les charges qu’il en déduit.
        </p>

        <div className={styles.row}>
          <Field
            label="Taille (cm)"
            inputMode="numeric"
            value={fields.height_cm}
            onChange={set('height_cm')}
          />
        </div>

        <div className={styles.row}>
          {/* L'année et non l'âge : un âge rangé est faux au premier anniversaire, et
              personne ne pense à le corriger. Le serveur en dérive l'âge. */}
          <Field
            label="Année de naissance"
            inputMode="numeric"
            value={fields.birth_year}
            onChange={set('birth_year')}
            hint={data.age === null ? undefined : `${String(data.age)} ans`}
          />
        </div>

        <div className={styles.row}>
          <Field
            label="Jours où je peux m’entraîner"
            value={fields.training_days}
            onChange={set('training_days')}
            placeholder="lundi, mercredi, samedi"
          />
        </div>

        <div className={styles.row}>
          <Field
            label="Matériel dont je dispose"
            value={fields.equipment}
            onChange={set('equipment')}
            placeholder="barre, disques, pas de rack"
          />
        </div>

        <div className={styles.row}>
          <Field
            label="Préférences d’entraînement"
            value={fields.preferences}
            onChange={set('preferences')}
            placeholder="ce qu’un coach devrait savoir avant de proposer une séance"
          />
        </div>

        <div className={styles.actions}>
          <Button
            variant="primary"
            busy={save.isPending}
            disabled={!dirty}
            onClick={() => {
              save.mutate(data);
            }}
          >
            {/* Nommé, comme « Enregistrer les rappels » juste au-dessous : trois sections
                de cet écran portent un bouton d'enregistrement, et trois « Enregistrer »
                nus ne se distinguent pas à la synthèse vocale. */}
            Enregistrer le profil
          </Button>
          {dirty && (
            <Button
              variant="quiet"
              onClick={() => {
                setDraft(null);
              }}
            >
              Annuler
            </Button>
          )}
        </div>
      </Card>

      {/* Ce qui part au modèle, montré tel quel. Même parti pris que le condensé publié
          sous une réponse : la promesse se vérifie à l'écran. */}
      <Card>
        <span className={styles.name}>Ce qui part à l’assistant</span>
        {data.lines.length === 0 ? (
          <p className={cx(styles.note, styles.noteSpaced)}>
            Rien pour l’instant. Chaque champ rempli ajoute une ligne — un champ vide n’en ajoute
            aucune, plutôt qu’une valeur par défaut qui serait fausse.
          </p>
        ) : (
          <ul className={styles.lines}>
            {data.lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
