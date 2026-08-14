/**
 * Le catalogue d'exercices, à son adresse — `/activite/catalogue`.
 *
 * Il a d'abord été une feuille ouverte depuis `/activite`. Une feuille plafonne à `86dvh`,
 * défile dans son propre conteneur et n'a pas d'adresse : à vingt exercices, on faisait
 * défiler une liste **dans** une page qui défilait déjà, et le bouton système « précédent »
 * refermait l'application au lieu du catalogue.
 *
 * C'est maintenant une page. Elle gagne trois choses qu'une feuille ne sait pas donner :
 * une URL qu'on garde en favori, une entrée dans l'historique de navigation, et toute la
 * hauteur de l'écran.
 *
 * **Le formulaire est en tête, replié.** Deux contraintes s'opposaient : déclarer un
 * exercice doit être atteignable sans défiler, et la liste — ce qu'on vient lire neuf fois
 * sur dix — ne doit pas commencer à 300 px du haut. Un bouton qui déplie le formulaire
 * juste sous lui satisfait les deux. Ce n'est **pas** une modale : rouvrir une popup dans
 * une route créée pour s'en passer n'aurait aucun sens.
 *
 * **`Retirer` et non `Supprimer`.** Le serveur ne touche pas au journal : les séries
 * passées restent lisibles sans le catalogue (`ACT-06`). Le mot suit l'acte.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import type { SyntheticEvent } from 'react';

import {
  Badge,
  Button,
  Card,
  Chip,
  ChipStrip,
  Empty,
  Field,
  LinkButton,
  PageHead,
  Rule,
} from '@/components/ui';
import { activityApi, type Exercise } from '@/features/activity/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { num, plural } from '@/lib/format';
import { keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from '../Activity.module.css';
import { useInvalidateActivity } from './shared';

/** Ce que la ligne dit d'elle-même : son passé, sans qu'on ait à ouvrir l'historique. */
function trace(item: Exercise): string {
  const consigned = `${String(item.entries)} ${plural(item.entries, 'série')}`;
  if (item.last_weight_kg == null) return consigned;
  const last = item.last_weight_kg === 0 ? 'poids du corps' : `${num(item.last_weight_kg, 1)} kg`;
  return `${consigned} · dernière ${last}`;
}

export function Catalogue() {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();

  const { data: groups } = useQuery({
    queryKey: keys.activity.muscleGroups(),
    queryFn: activityApi.muscleGroups,
  });
  const {
    data: catalogue,
    isPending,
    error: unreadable,
  } = useQuery({
    queryKey: keys.activity.exercises(),
    queryFn: activityApi.exercises,
  });

  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const [group, setGroup] = useState('pectoraux');
  const [editing, setEditing] = useState<Exercise | null>(null);
  const [armed, setArmed] = useState<number | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const shown = adding || editing !== null;

  // Le formulaire est **au-dessus** de la liste : appuyer sur « Corriger » à la quinzième
  // ligne ne montrerait rien du tout sans ce défilement. Il remonte, il ne descend pas —
  // c'est l'inverse de ce que faisait la feuille, et c'est pour la même raison.
  const formRef = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (!shown) return;
    formRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
  }, [shown, editing]);

  function close(): void {
    setAdding(false);
    setEditing(null);
    setName('');
    setGroup('pectoraux');
    setError(null);
  }

  const save = useMutation({
    mutationFn: () =>
      editing === null
        ? activityApi.createExercise(name.trim(), group)
        : activityApi.updateExercise(editing.id, editing.token, name.trim(), group),
    onSuccess: () => {
      invalidate();
      notify(editing === null ? 'Exercice ajouté au catalogue.' : 'Exercice corrigé.', 'signal');
      close();
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
      if (caught instanceof ApiError && caught.code === 'conflict') invalidate();
    },
  });

  const remove = useMutation({
    mutationFn: (item: Exercise) => activityApi.deleteExercise(item.id, item.token),
    onSuccess: (_removed, item) => {
      setArmed(null);
      // La ligne en cours de correction vient de disparaître : le formulaire ne doit pas
      // rester braqué sur elle, il enverrait un jeton qui ne désigne plus rien.
      if (editing?.id === item.id) close();
      invalidate();
      notify('Exercice retiré. Les séries consignées restent au journal.', 'signal');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Retrait impossible.', 'recover');
      setArmed(null);
      invalidate();
    },
  });

  function submit(event: SyntheticEvent): void {
    event.preventDefault();
    save.mutate();
  }

  const entries = catalogue ?? [];

  return (
    <div className={cx('wrap', styles.screen)}>
      <PageHead
        eyebrow="Domaine Activité"
        title="Catalogue d’exercices"
        actions={
          <>
            {/* L'action que la page sert à porter, et elle est au-dessus de la ligne de
                flottaison : la déclarer ne demande aucun défilement. */}
            <Button
              variant="primary"
              aria-expanded={shown}
              onClick={() => {
                if (shown) {
                  close();
                  return;
                }
                setAdding(true);
              }}
            >
              {shown ? 'Fermer le formulaire' : 'Ajouter un exercice'}
            </Button>
            <LinkButton variant="quiet" to="/activite">
              Retour à l’activité
            </LinkButton>
          </>
        }
      >
        À déclarer une fois : l’exercice devient ensuite proposé dans le journal.
      </PageHead>

      {shown && (
        <Card>
          <h3>{editing === null ? 'Déclarer un exercice' : `Corriger « ${editing.name} »`}</h3>

          <form className={styles.form} onSubmit={submit} ref={formRef} noValidate>
            {error !== null && (
              <p className={styles.error} role="alert">
                {error.message}
              </p>
            )}

            {/* Ce que le geste coûte, dit avant le geste : la correction se répercute sur
                les séries déjà consignées, et rien ne la défait. */}
            {editing !== null && editing.entries > 0 && (
              <p className={styles.note}>
                {editing.entries === 1
                  ? 'Corriger le nom ou le groupe met aussi à jour la série déjà consignée.'
                  : `Corriger le nom ou le groupe met aussi à jour les ${String(editing.entries)} séries déjà consignées.`}
              </p>
            )}

            <Field
              label="Nom"
              placeholder="Développé couché"
              value={name}
              error={error?.messageFor('name')}
              onChange={(event) => {
                setName(event.target.value);
              }}
            />

            {/* Neuf valeurs fermées : des pastilles, pas une liste déroulante native. */}
            <ChipStrip label="Groupe musculaire">
              {(groups ?? []).map((item) => (
                <Chip
                  key={item}
                  selected={group === item}
                  onClick={() => {
                    setGroup(item);
                  }}
                >
                  {item}
                </Chip>
              ))}
            </ChipStrip>

            <div className={styles.sheetCommit}>
              <Button
                type="submit"
                variant="primary"
                className={styles.commit}
                busy={save.isPending}
                disabled={name.trim() === ''}
              >
                {editing === null ? 'Ajouter au catalogue' : 'Enregistrer'}
              </Button>
              <Button variant="quiet" onClick={close}>
                Annuler
              </Button>
            </div>
          </form>
        </Card>
      )}

      <Rule>
        {catalogue === undefined
          ? 'Exercices'
          : `${String(entries.length)} ${plural(entries.length, 'exercice')}`}
      </Rule>

      <Card>
        {unreadable !== null ? (
          <p className={styles.error} role="alert">
            {unreadable instanceof ApiError ? unreadable.message : 'Catalogue illisible.'}
          </p>
        ) : isPending ? (
          <p className={styles.empty}>chargement…</p>
        ) : entries.length === 0 ? (
          <Empty title="Catalogue vide">
            Un exercice déclaré, et le journal sait quoi te proposer. Son nom et son groupe
            musculaire suffisent.
          </Empty>
        ) : (
          <ul className={styles.catalogue} aria-label="Exercices déclarés">
            {entries.map((item) => (
              <li className={styles.catalogueRow} key={item.exercise_id}>
                <div className={styles.catalogueBody}>
                  <div className={styles.catalogueHead}>
                    <span>{item.name}</span>
                    <Badge tone="signal">{item.muscle_group}</Badge>
                  </div>
                  <span className={styles.entryDetail}>{trace(item)}</span>
                </div>

                {/* Des pastilles et non des boutons discrets : sans bordure, « Corriger »
                    et « Retirer » se lisaient comme du texte posé sous la ligne. C'est le
                    vocabulaire des actions de ligne de l'historique. */}
                <div className={styles.catalogueActions}>
                  {/* Le nom accessible désigne **quel** exercice : autant de « Corriger »
                      nus que de lignes ne se distinguent pas à la synthèse vocale. */}
                  <Chip
                    aria-label={`Corriger ${item.name}`}
                    onClick={() => {
                      setAdding(false);
                      setEditing(item);
                      setName(item.name);
                      setGroup(item.muscle_group);
                      setError(null);
                    }}
                  >
                    Corriger
                  </Chip>
                  {/* Deux appuis pour détruire : le projet n'a pas d'annulation. */}
                  <Chip
                    className={cx(armed === item.id && styles.armed)}
                    disabled={remove.isPending}
                    aria-label={
                      armed === item.id
                        ? `Retirer ${item.name} du catalogue — confirmer`
                        : `Retirer ${item.name} du catalogue`
                    }
                    onClick={() => {
                      if (armed !== item.id) {
                        setArmed(item.id);
                        return;
                      }
                      remove.mutate(item);
                    }}
                  >
                    {armed === item.id ? 'Confirmer ?' : 'Retirer'}
                  </Chip>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
