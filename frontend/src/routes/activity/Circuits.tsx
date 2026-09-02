/**
 * Les séances Cadence, à leur adresse — `/activite/seances`.
 *
 * Une **page** et non une feuille, pour la même raison que le catalogue : un circuit à
 * huit exercices ne tient pas dans un panneau à `86dvh` qui défile dans une page qui
 * défile déjà, et le bouton système « précédent » doit refermer la liste, pas
 * l'application.
 *
 * ── Ce que cet écran ne calcule pas ───────────────────────────────────────
 *
 * **Ni le lien, ni la durée.** `circuit.url` arrive fabriqué par le serveur — l'échappement
 * des noms, le bornage à 99 rounds et le suffixe qui distingue quinze répétitions de quinze
 * secondes sont des règles métier, pas du formatage. `estimated_duration_min` arrive
 * calculée. L'écran pose l'un dans un `href` et formate l'autre.
 *
 * ── Le `~` devant une durée ───────────────────────────────────────────────
 *
 * `exact` est faux dès qu'un exercice est en répétitions : personne ne sait combien de
 * temps prend une série. Afficher « 18 min » dans ce cas serait une valeur inventée, et
 * Cadence lui-même préfixe ces totaux d'un tilde. Les deux applications disent donc la
 * même chose de la même séance.
 *
 * ── Deux appuis pour détruire, un seul pour consigner ─────────────────────
 *
 * Supprimer un circuit s'arme puis s'exécute — le projet n'a aucune annulation. Déclarer
 * une séance faite, non : c'est une **addition**, elle se défait par la suppression que
 * l'utilisateur ferait de toute façon. Demander confirmation partout finit par la faire
 * ignorer là où elle compte.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { SyntheticEvent } from 'react';

import {
  Badge,
  Button,
  Card,
  Chip,
  ChipStrip,
  Combobox,
  Empty,
  Field,
  LinkButton,
  PageHead,
  Rule,
  Segmented,
} from '@/components/ui';
import { activityApi, type Circuit, type CircuitPayload } from '@/features/activity/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { plural } from '@/lib/format';
import { keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from '../Activity.module.css';
import { CircuitCard } from './CircuitCard';
import { MODES, NEW_LINE, toDrafts, toPayload, useInvalidateActivity, type Draft } from './shared';

export function Circuits() {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();

  const { data: groups } = useQuery({
    queryKey: keys.activity.muscleGroups(),
    queryFn: activityApi.muscleGroups,
  });
  const {
    data,
    isPending,
    error: unreadable,
  } = useQuery({
    queryKey: keys.activity.circuits(),
    queryFn: activityApi.circuits,
  });
  /**
   * Ce qu'on tape dans le champ d'exercice **en cours**, une seule fois pour toutes les
   * lignes : c'est ce qui pilote la recherche au serveur.
   *
   * Une par ligne ferait autant de requêtes que d'exercices dans le formulaire, pour un
   * seul champ visible à la fois — le clavier n'est ouvert que sur un.
   */
  const [search, setSearch] = useState('');

  /**
   * Les noms proposés à la saisie — **cherchés au serveur, jamais écrits ici.**
   *
   * Cadence embarque 1324 démonstrations. Les recopier ici mettrait 70 ko dans le paquet
   * de l'application et les ferait diverger du jour où elle en ajoute une ; les servir
   * d'un bloc ferait filtrer un téléphone. Le serveur cherche, l'écran affiche.
   */
  const { data: catalogue } = useQuery({
    queryKey: keys.activity.circuitExercises(search),
    queryFn: () => activityApi.circuitExercises(search),
  });

  const suggestions = useMemo(
    () =>
      (catalogue ?? []).map((item) => ({
        value: item.name,
        // Ce que le catalogue sait de cet exercice, dit là où on le choisit : la zone du
        // corps pour un nom de Cadence, le groupe musculaire pour un des siens.
        hint: item.body_part ?? item.muscle_group ?? undefined,
      })),
    [catalogue],
  );

  /** Le groupe déjà déclaré pour cet exercice, ou `null` s'il n'est pas au catalogue. */
  function groupOf(name: string): string | null {
    return (catalogue ?? []).find((item) => item.name === name)?.muscle_group ?? null;
  }

  const [editing, setEditing] = useState<Circuit | null>(null);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [rounds, setRounds] = useState('4');
  const [roundRest, setRoundRest] = useState('60');
  const [lines, setLines] = useState<Draft[]>([{ ...NEW_LINE }]);
  const [link, setLink] = useState('');
  const [armed, setArmed] = useState<number | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const shown = open || editing !== null;

  // Le formulaire est **au-dessus** de la liste : appuyer sur « Corriger » à la sixième
  // ligne ne montrerait rien sans ce défilement. Même geste que le catalogue.
  const formRef = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (!shown) return;
    formRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
  }, [shown, editing]);

  function close(): void {
    setOpen(false);
    setEditing(null);
    setName('');
    setRounds('4');
    setRoundRest('60');
    setLines([{ ...NEW_LINE }]);
    setError(null);
  }

  function edit(circuit: Circuit): void {
    setOpen(false);
    setEditing(circuit);
    setName(circuit.name);
    setRounds(String(circuit.rounds));
    setRoundRest(String(circuit.round_rest_s));
    setLines(toDrafts(circuit));
    setError(null);
  }

  const payload = toPayload(name, rounds, roundRest, lines);

  const save = useMutation({
    mutationFn: (body: CircuitPayload) =>
      editing === null
        ? activityApi.createCircuit(body)
        : activityApi.updateCircuit(editing.id, editing.token, body),
    onSuccess: () => {
      invalidate();
      notify(editing === null ? 'Séance enregistrée.' : 'Séance corrigée.', 'signal');
      close();
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
      if (caught instanceof ApiError && caught.code === 'conflict') invalidate();
    },
  });

  const paste = useMutation({
    mutationFn: () => activityApi.importCircuit(link.trim()),
    onSuccess: (created) => {
      invalidate();
      setLink('');
      // Le lien ne porte aucun groupe musculaire — le format Cadence n'a pas de champ pour
      // ça. On le dit, plutôt que de laisser « autre » se découvrir dans les statistiques.
      notify(`« ${created.name} » importée. Corrige ses groupes musculaires.`, 'signal');
      edit(created);
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Lien illisible.', 'recover');
    },
  });

  const remove = useMutation({
    mutationFn: (circuit: Circuit) => activityApi.deleteCircuit(circuit.id, circuit.token),
    onSuccess: (_gone, circuit) => {
      setArmed(null);
      if (editing?.id === circuit.id) close();
      invalidate();
      notify('Séance supprimée. Les séances déjà consignées restent au journal.', 'signal');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Suppression impossible.', 'recover');
      setArmed(null);
      invalidate();
    },
  });

  function submit(event: SyntheticEvent): void {
    event.preventDefault();
    if (payload !== null) save.mutate(payload);
  }

  function setLine(index: number, patch: Partial<Draft>): void {
    setLines((current) => current.map((line, at) => (at === index ? { ...line, ...patch } : line)));
  }

  const circuits = data?.circuits ?? [];

  return (
    <div className={cx('wrap', styles.screen)}>
      <PageHead
        eyebrow="Domaine Activité"
        title="Séances Cadence"
        actions={
          <>
            <Button
              variant="primary"
              aria-expanded={shown}
              onClick={() => {
                if (shown) {
                  close();
                  return;
                }
                setOpen(true);
              }}
            >
              {shown ? 'Fermer le formulaire' : 'Créer une séance'}
            </Button>
            <LinkButton variant="quiet" to="/activite/creer">
              Composer avec l’assistant
            </LinkButton>
            <LinkButton variant="quiet" to="/activite">
              Retour à l’activité
            </LinkButton>
          </>
        }
      >
        Une séance construite ici s’ouvre dans Cadence Tabata. La déclarer faite l’écrit au journal,
        avec ses séries.
      </PageHead>

      {/* L'état de configuration se dit **avant** la liste : sans adresse, aucun bouton
          « Ouvrir » n'existe, et le découvrir ligne par ligne serait une énigme. */}
      {data !== undefined && !data.linkable && (
        <Card>
          <div className="spread">
            <span className={styles.dayName}>Adresse de Cadence non renseignée</span>
            <Badge tone="load">en sommeil</Badge>
          </div>
          <p className={cx(styles.note, styles.spaced)}>
            Les séances se créent et se déclarent faites, mais aucune ne s’ouvre. L’adresse se règle
            une fois.
          </p>
          <LinkButton to="/reglages">Aller aux réglages</LinkButton>
        </Card>
      )}

      {shown && (
        <Card>
          <h3>{editing === null ? 'Nouvelle séance' : `Corriger « ${editing.name} »`}</h3>

          <form
            className={cx(styles.form, styles.circuitForm)}
            onSubmit={submit}
            ref={formRef}
            noValidate
          >
            {error !== null && error.fields.length === 0 && (
              <p className={styles.error} role="alert">
                {error.message}
              </p>
            )}

            <Field
              label="Nom de la séance"
              placeholder="Haut du corps"
              value={name}
              error={error?.messageFor('name')}
              onChange={(event) => {
                setName(event.target.value);
              }}
            />

            <div className={styles.circuitTop}>
              <Field
                label="Rounds"
                inputMode="numeric"
                value={rounds}
                error={error?.messageFor('rounds')}
                onChange={(event) => {
                  setRounds(event.target.value);
                }}
              />
              <Field
                label="Repos entre rounds (s)"
                inputMode="numeric"
                value={roundRest}
                error={error?.messageFor('round_rest_s')}
                onChange={(event) => {
                  setRoundRest(event.target.value);
                }}
              />
            </div>

            {lines.map((line, index) => (
              <div className={styles.circuitLine} key={index}>
                {/* Un combobox et non un champ nu : la liste des noms se réduit à chaque
                    frappe, `Tab` écrit le premier résultat, et choisir une suggestion
                    pré-remplit le groupe musculaire quand l'exercice est déjà au catalogue.

                    **L'indice disait « écris-le en français ».** C'était vrai des 35 noms
                    d'avant ; le catalogue en porte 1324, tous anglais, et « pompes » n'y
                    trouve rien. Un indice faux coûte plus qu'aucun indice : il fait
                    chercher là où il n'y a rien.

                    Le champ **reste libre** — un nom hors liste s'enregistre. Ces
                    suggestions ne sont pas des valeurs autorisées : n'importe quel
                    intitulé fait tourner une séance, il perd seulement son illustration. */}
                <Combobox
                  label={`Exercice ${String(index + 1)}`}
                  placeholder="push-up"
                  value={line.name}
                  options={suggestions}
                  hint="Les noms du catalogue sont en anglais — cherche « push up », « plank »"
                  onChange={(name) => {
                    setLine(index, { name });
                    setSearch(name);
                  }}
                  onSelect={(option) => {
                    // Le groupe vient du catalogue de l'utilisateur, jamais deviné depuis
                    // le nom : un exercice inconnu laisse le sélecteur où il est.
                    const group = groupOf(option.value);
                    if (group !== null) setLine(index, { name: option.value, muscle_group: group });
                  }}
                />

                {/* Le groupe musculaire est **exigé** : c'est lui qui fait qu'un tabata
                    compte dans l'équilibre par groupe une fois déclaré fait. Le deviner
                    depuis un nom anglais serait une correspondance qui se trompe en
                    silence. */}
                <ChipStrip label="Groupe musculaire">
                  {(groups ?? []).map((group) => (
                    <Chip
                      key={group}
                      selected={line.muscle_group === group}
                      onClick={() => {
                        setLine(index, { muscle_group: group });
                      }}
                    >
                      {group}
                    </Chip>
                  ))}
                </ChipStrip>

                {/* Secondes ou répétitions : c'est **le** choix qui change la nature de
                    l'exercice, et le confondre est la faute la plus fréquente du format.
                    Un sélecteur explicite plutôt qu'un suffixe à taper. */}
                <Segmented
                  label={`Nature de l’exercice ${String(index + 1)}`}
                  options={MODES}
                  value={line.mode}
                  onChange={(mode) => {
                    setLine(index, { mode });
                  }}
                />

                <div className={styles.circuitNums}>
                  <Field
                    label={line.mode === 'time' ? 'Secondes' : 'Répétitions'}
                    inputMode="numeric"
                    value={line.value}
                    onChange={(event) => {
                      setLine(index, { value: event.target.value });
                    }}
                  />
                  <Field
                    label="Repos après (s)"
                    inputMode="numeric"
                    value={line.rest}
                    onChange={(event) => {
                      setLine(index, { rest: event.target.value });
                    }}
                  />
                </div>

                {/* Le 4ᵉ champ du lien : ce que Cadence affiche sous le nom pendant
                    l'effort, et sur la carte « PROCHAIN » du repos qui précède
                    (`llms.txt` §10). Une ligne, pas plus — au-delà, ça pousse le reste
                    hors de l'écran de quelqu'un qui force, et le serveur refuse.

                    **La charge ne se retape pas ici.** Elle vient de `circuit_loads.csv`
                    et se joint à la note au moment de fabriquer le lien : l'écrire à la
                    main la figerait, et elle cesserait de suivre les changements de la
                    page Charges. */}
                <Field
                  // Sans indice, comme « Secondes » et « Repos après » juste au-dessus :
                  // la carte porte déjà « Exercice 1 », et trois libellés numérotés sur
                  // cinq qui ne le sont pas se lisent comme une incohérence.
                  label="Note pendant l’effort"
                  value={line.note}
                  maxLength={60}
                  hint="Ce que Cadence montre sous le nom. La charge s’y ajoute toute seule."
                  placeholder="genoux au sol, tempo lent…"
                  onChange={(event) => {
                    setLine(index, { note: event.target.value });
                  }}
                />

                {lines.length > 1 && (
                  <Chip
                    aria-label={`Retirer l’exercice ${String(index + 1)}`}
                    onClick={() => {
                      setLines((current) => current.filter((_line, at) => at !== index));
                    }}
                  >
                    Retirer cet exercice
                  </Chip>
                )}
              </div>
            ))}

            <Button
              variant="ghost"
              onClick={() => {
                setLines((current) => [...current, { ...NEW_LINE }]);
              }}
            >
              Ajouter un exercice
            </Button>

            <div className={styles.sheetCommit}>
              <Button
                type="submit"
                variant="primary"
                className={styles.commit}
                busy={save.isPending}
                disabled={payload === null}
              >
                {editing === null ? 'Enregistrer la séance' : 'Enregistrer'}
              </Button>
              <Button variant="quiet" onClick={close}>
                Annuler
              </Button>
            </div>
          </form>
        </Card>
      )}

      <Rule>
        {data === undefined
          ? 'Séances'
          : `${String(circuits.length)} ${plural(circuits.length, 'séance')}`}
      </Rule>

      <Card>
        {unreadable !== null ? (
          <p className={styles.error} role="alert">
            {unreadable instanceof ApiError ? unreadable.message : 'Séances illisibles.'}
          </p>
        ) : isPending ? (
          <p className={styles.empty}>chargement…</p>
        ) : circuits.length === 0 ? (
          <Empty title="Aucune séance">
            Une séance créée ici s’ouvre dans Cadence d’un appui, et se consigne au journal quand
            elle est faite. Un nom, un nombre de rounds, un exercice.
          </Empty>
        ) : (
          <ul className={styles.catalogue} aria-label="Séances Cadence">
            {circuits.map((circuit) => (
              <li className={styles.catalogueRow} key={circuit.circuit_id || circuit.id}>
                <CircuitCard
                  circuit={circuit}
                  actions={
                    <>
                      <Chip
                        aria-label={`Corriger ${circuit.name}`}
                        onClick={() => {
                          edit(circuit);
                        }}
                      >
                        Corriger
                      </Chip>
                      {/* Deux appuis pour détruire : le projet n'a pas d'annulation. */}
                      <Chip
                        className={cx(armed === circuit.id && styles.armed)}
                        disabled={remove.isPending}
                        aria-label={
                          armed === circuit.id
                            ? `Supprimer ${circuit.name} — confirmer`
                            : `Supprimer ${circuit.name}`
                        }
                        onClick={() => {
                          if (armed !== circuit.id) {
                            setArmed(circuit.id);
                            return;
                          }
                          remove.mutate(circuit);
                        }}
                      >
                        {armed === circuit.id ? 'Confirmer ?' : 'Supprimer'}
                      </Chip>
                    </>
                  }
                />
              </li>
            ))}
          </ul>
        )}
      </Card>

      {!shown && (
        <Card>
          <h3>Coller un lien Cadence</h3>
          <p className={cx(styles.note, styles.spaced)}>
            Une séance déjà construite dans Cadence redevient modifiable ici. Ses groupes
            musculaires restent à choisir : le lien n’en porte aucun.
          </p>
          <div className={styles.spaced}>
            <Field
              label="Adresse de la séance"
              type="url"
              inputMode="url"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              value={link}
              onChange={(event) => {
                setLink(event.target.value);
              }}
            />
          </div>
          <div className={styles.sheetCommit}>
            <Button
              variant="ghost"
              busy={paste.isPending}
              disabled={link.trim() === ''}
              onClick={() => {
                paste.mutate();
              }}
            >
              Relire ce lien
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}
