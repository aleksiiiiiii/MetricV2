import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { Button, Card, Chip, Empty, Field, Rule } from '@/components/ui';
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
  /** Les valeurs du catalogue cochées. Un tableau et non une chaîne : c'est une liste
   *  fermée, et la sérialiser ici puis la relire serait un format de plus à tenir. */
  equipment: string[];
  preferences: string;
  constraints: string;
}

function toDraft(view: ProfileView): Draft {
  return {
    height_cm: view.height_cm === null ? '' : String(view.height_cm),
    birth_year: view.birth_year === null ? '' : String(view.birth_year),
    training_days: view.training_days,
    equipment: view.equipment,
    preferences: view.preferences,
    constraints: view.constraints,
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
    equipment: draft.equipment,
    preferences: draft.preferences.trim(),
    constraints: draft.constraints.trim(),
  };
}

function same(a: Draft, b: Draft): boolean {
  return (
    a.height_cm === b.height_cm &&
    a.birth_year === b.birth_year &&
    a.training_days === b.training_days &&
    a.equipment.join() === b.equipment.join() &&
    a.preferences === b.preferences &&
    a.constraints === b.constraints
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
  /** Le dépliant du matériel rare. Fermé d'entrée : douze cases se parcourent, vingt-huit
   *  poussent hors de vue les trois qu'on possède vraiment. */
  const [allEquipment, setAllEquipment] = useState(false);

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
  const set =
    (key: 'height_cm' | 'birth_year' | 'training_days' | 'preferences' | 'constraints') =>
    (event: { target: { value: string } }) => {
      setDraft({ ...fields, [key]: event.target.value });
    };

  /**
   * Cocher ou décocher un matériel.
   *
   * **La forme fonctionnelle de `setDraft`, contrairement à `set` juste au-dessus.** Deux
   * pastilles cochées coup sur coup lisaient toutes deux le même `fields` figé, et la
   * seconde écrasait la première : « dumbbell » puis « band » ne laissait que « band ».
   * Trouvé en pilotant l'écran, pas par un test — les deux appuis y sont séparés par un
   * rendu, ce qui masque exactement le défaut. Un champ de texte n'a pas ce problème : on
   * n'en remplit qu'un à la fois.
   *
   * L'ordre est celui du serveur et non celui des appuis : c'est lui qui décide de l'ordre
   * de la ligne envoyée au modèle.
   */
  const toggle = (value: string) => () => {
    setDraft((current) => {
      const base = current ?? toDraft(data);
      const owned = new Set(base.equipment);
      if (owned.has(value)) owned.delete(value);
      else owned.add(value);
      return {
        ...base,
        equipment: data.equipment_catalogue
          .map((item) => item.value)
          .filter((item) => owned.has(item)),
      };
    });
  };

  const shown = data.equipment_catalogue.filter(
    // Un matériel coché reste visible même s'il est « rare » : le replier sous un
    // dépliant fermé ferait croire qu'il a été décoché.
    (item) => item.common || allEquipment || fields.equipment.includes(item.value),
  );
  const hidden = data.equipment_catalogue.length - shown.length;

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

        {/* Une liste fermée et non un champ libre, et c'est ce qui rend le réglage utile :
            ces valeurs filtrent la recherche d'exercices servie à l'assistant. « haltères
            10 kg » écrit à la main ne filtrerait rien.

            Les noms restent ceux du catalogue Cadence, en anglais : c'est avec eux que le
            modèle cherche, et une traduction à l'écran serait un second vocabulaire pour
            la même chose. */}
        <div className={styles.row}>
          <span className={styles.name} id="equipment-label">
            Matériel dont je dispose
          </span>
          <p className={cx(styles.note, styles.noteSpaced)}>
            Ce qui est coché limite ce que l’assistant propose. Le poids du corps reste toujours
            possible, coché ou non.
          </p>
          <div className={styles.chips} role="group" aria-labelledby="equipment-label">
            {shown.map((item) => (
              <Chip
                key={item.value}
                selected={fields.equipment.includes(item.value)}
                onClick={toggle(item.value)}
              >
                {item.value}
              </Chip>
            ))}
          </div>
          {hidden > 0 && (
            <Button
              variant="quiet"
              className={styles.disclose}
              onClick={() => {
                setAllEquipment(true);
              }}
            >
              Tout le matériel ({hidden} de plus)
            </Button>
          )}
        </div>

        {/* Ce que la cellule portait avant que le champ soit fermé sur le catalogue.
            Montré plutôt que jeté en silence : une donnée ne s'invente pas, et elle ne
            s'évapore pas non plus. Le prochain enregistrement l'efface — et c'est alors
            un geste, avec les cases sous les yeux. */}
        {data.equipment_unknown.length > 0 && (
          <p className={cx(styles.note, styles.noteSpaced)}>
            Le profil portait « {data.equipment_unknown.join(', ')} », que le catalogue Cadence ne
            reconnaît pas — ce texte ne part pas à l’assistant. Coche ce qui correspond ci-dessus :
            le prochain enregistrement le remplacera.
          </p>
        )}

        <div className={styles.row}>
          <Field
            label="Préférences d’entraînement"
            value={fields.preferences}
            onChange={set('preferences')}
            placeholder="ce qu’un coach devrait savoir avant de proposer une séance"
          />
        </div>

        {/* Un champ à part des préférences, et la distinction porte tout le sens : une
            préférence se contourne, une contrainte est un refus. Les mélanger ôterait au
            modèle le moyen de savoir laquelle il a le droit d'ignorer. */}
        <div className={styles.row}>
          <Field
            label="Contraintes à respecter"
            value={fields.constraints}
            onChange={set('constraints')}
            placeholder="épaule droite sensible, pas de banc"
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
