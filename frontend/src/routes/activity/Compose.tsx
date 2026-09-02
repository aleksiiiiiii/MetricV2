import { useMutation, useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';

import {
  AiBlock,
  Badge,
  Button,
  Card,
  Combobox,
  Empty,
  Field,
  LinkButton,
  PageHead,
  Rule,
  Segmented,
  Stepper,
} from '@/components/ui';
import { activityApi, type CircuitPayload, type CircuitProposal } from '@/features/activity/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { plural } from '@/lib/format';
import { keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from '../Activity.module.css';
import { MODES, toPayload, useInvalidateActivity, type Draft } from './shared';

/**
 * `/activite/creer` — une phrase, un circuit ajustable (**R5**).
 *
 * ── Le partage du travail ─────────────────────────────────────────────────
 *
 * **Le modèle propose, l'écran laisse ajuster, l'appui écrit.** Les trois temps sont
 * séparés jusque dans le réseau : `composeCircuit` n'écrit rien, `createCircuit` ne
 * connaît pas l'IA, et entre les deux il y a cet écran. Un circuit à dix exercices se
 * corrige mal une fois enregistré — c'est toute la raison d'être de la page.
 *
 * ── Aucune cinquième façon de dire « proposé » ────────────────────────────
 *
 * `AiBlock` pour le bloc, l'état `proposed` du `Stepper` pour chaque valeur. Le
 * vocabulaire existe et sert déjà à la nutrition et à l'import Apple ; en inventer un
 * cinquième affaiblirait les quatre autres.
 *
 * **La marque disparaît dès qu'on touche la valeur** : corriger, c'est s'approprier. Le
 * suivi est par ligne et par champ, sinon retoucher les répétitions du premier exercice
 * dédouanerait le repos du dernier.
 *
 * ── Ce que l'écran ne fabrique pas ────────────────────────────────────────
 *
 * Ni lien Cadence (**D7** — le serveur le fabrique à la lecture du circuit enregistré),
 * ni durée estimée, ni groupe musculaire deviné. Tout ce qui s'affiche ici a été décidé
 * ailleurs ; l'écran assemble.
 */

/** Ce qui a été retouché, par indice de ligne et par champ. `-1` porte l'en-tête. */
type Touched = Record<string, true>;

function key(line: number, field: string): string {
  return `${String(line)}.${field}`;
}

function toDrafts(proposal: CircuitProposal): Draft[] {
  return proposal.exercises.map((item) => ({
    name: item.name,
    muscle_group: item.muscle_group,
    mode: item.reps === null ? 'time' : 'reps',
    value: String(item.reps ?? item.duration_s ?? ''),
    rest: String(item.rest_s),
    // **Le modèle ne propose pas de note.** Elle porte ce que l'application n'a aucun
    // moyen de savoir — « genoux au sol », « épaule qui tire » — donc lui non plus. Une
    // note inventée s'afficherait sous le nom pendant l'effort et se croirait.
    note: '',
  }));
}

export function Compose() {
  const navigate = useNavigate();
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();

  const { data: groups } = useQuery({
    queryKey: keys.activity.muscleGroups(),
    queryFn: activityApi.muscleGroups,
  });

  /**
   * Ce qui est tapé dans le champ de nom en cours. Un seul état pour toutes les lignes :
   * on n'en édite qu'une à la fois, et une recherche par ligne ferait autant de requêtes
   * ouvertes qu'il y a d'exercices.
   */
  const [search, setSearch] = useState('');

  /**
   * Le catalogue **cherché par le serveur**, jamais recopié ici.
   *
   * Cadence embarque 1324 démonstrations. Les mettre dans le paquet de l'application les
   * ferait diverger du jour où elle en ajoute une ; les servir d'un bloc ferait filtrer un
   * téléphone. Le serveur cherche, l'écran affiche — c'est le même arrangement que le
   * formulaire manuel, et la même requête.
   */
  const { data: catalogue } = useQuery({
    queryKey: keys.activity.circuitExercises(search),
    queryFn: () => activityApi.circuitExercises(search),
  });

  const suggestions = useMemo(
    () =>
      (catalogue ?? []).map((item) => ({
        value: item.name,
        hint: item.body_part ?? item.muscle_group ?? undefined,
      })),
    [catalogue],
  );

  /** Le groupe déjà déclaré pour ce nom, ou `null` s'il n'est pas au catalogue de Metric. */
  function groupOf(name: string): string | null {
    return (catalogue ?? []).find((item) => item.name === name)?.muscle_group ?? null;
  }

  const [wish, setWish] = useState('');
  const [proposal, setProposal] = useState<CircuitProposal | null>(null);
  const [name, setName] = useState('');
  const [rounds, setRounds] = useState('');
  const [rest, setRest] = useState('');
  const [lines, setLines] = useState<Draft[]>([]);
  const [touched, setTouched] = useState<Touched>({});

  const compose = useMutation({
    mutationFn: () => activityApi.composeCircuit(wish),
    onSuccess: (found) => {
      setProposal(found);
      setName(found.name);
      setRounds(String(found.rounds));
      setRest(String(found.round_rest_s));
      setLines(toDrafts(found));
      // Une nouvelle proposition **remet toutes les marques** : les valeurs viennent
      // d'arriver, aucune n'a encore été approuvée.
      setTouched({});
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Proposition impossible.', 'recover');
    },
  });

  // La charge utile est construite **avant** l'appel et passée en argument : le bouton
  // est désactivé tant qu'elle vaut `null`, donc fabriquer ici une erreur cliente pour un
  // cas inatteignable serait un chemin que rien ne parcourt jamais.
  const save = useMutation({
    mutationFn: (payload: CircuitPayload) => activityApi.createCircuit(payload),
    onSuccess: () => {
      invalidate();
      notify(`« ${name.trim()} » enregistrée.`, 'effort');
      void navigate('/activite/seances');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Enregistrement impossible.', 'recover');
    },
  });

  const mark = (line: number, field: string) => {
    setTouched((current) => ({ ...current, [key(line, field)]: true }));
  };

  const proposed = (line: number, field: string): boolean =>
    proposal !== null && touched[key(line, field)] !== true;

  const edit = (index: number, patch: Partial<Draft>, field: string) => {
    mark(index, field);
    setLines((current) =>
      current.map((line, position) => (position === index ? { ...line, ...patch } : line)),
    );
  };

  const payload = toPayload(name, rounds, rest, lines);

  return (
    <div className={cx('wrap', styles.screen)}>
      <PageHead
        eyebrow="Activité"
        title="Composer une séance"
        actions={
          <LinkButton variant="quiet" to="/activite/seances">
            Toutes les séances
          </LinkButton>
        }
      >
        Décris ce que tu veux en une phrase. Ton matériel et les groupes que tu n’as pas travaillés
        depuis longtemps partent avec la demande — tu n’as pas à les retaper.
      </PageHead>

      <Card>
        <Field
          label="Ce que tu veux"
          value={wish}
          onChange={(event) => {
            setWish(event.target.value);
          }}
          placeholder="bras 30 min, un haltère de 10 kg"
        />
        <div className={styles.composeAction}>
          <Button
            variant="primary"
            busy={compose.isPending}
            onClick={() => {
              compose.mutate();
            }}
          >
            {proposal === null ? 'Proposer une séance' : 'Proposer autre chose'}
          </Button>
        </div>
      </Card>

      {proposal === null && !compose.isPending && (
        <Card>
          <Empty title="Rien de proposé pour l’instant">
            Une phrase suffit — et même une phrase vide : ce que l’application sait déjà de toi lui
            donne de quoi composer. Rien n’est enregistré tant que tu n’as pas appuyé sur «
            Enregistrer ».
          </Empty>
        </Card>
      )}

      {proposal !== null && (
        <>
          <Rule>La proposition</Rule>

          <AiBlock tag="Proposé">
            {/* Ce sur quoi elle s'appuie, dit avant elle. Une suggestion dont on voit
                l'argument se discute ; une suggestion nue se croit ou se rejette. */}
            <ul className={styles.composeBasis}>
              {proposal.basis.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>

            <div className={styles.composeRow}>
              <Field
                label="Nom de la séance"
                value={name}
                onChange={(event) => {
                  mark(-1, 'name');
                  setName(event.target.value);
                }}
              />
            </div>

            <div className={styles.composePair}>
              <Stepper
                label="Rounds"
                value={rounds}
                proposed={proposed(-1, 'rounds')}
                onChange={(value) => {
                  mark(-1, 'rounds');
                  setRounds(value);
                }}
              />
              <Stepper
                label="Repos entre rounds (s)"
                value={rest}
                step={10}
                proposed={proposed(-1, 'rest')}
                onChange={(value) => {
                  mark(-1, 'rest');
                  setRest(value);
                }}
              />
            </div>
          </AiBlock>

          {lines.map((line, index) => (
            // La position et non le nom : une clé qui contient la valeur change à chaque
            // frappe, donc React démonte la carte et remonte le champ — le focus part, et
            // la deuxième lettre tombe dans le vide. C'est-à-dire qu'on ne pouvait pas
            // taper un nom d'exercice. Trouvé en tapant, pas en mesurant.
            <Card key={index}>
              <div className={styles.composeHead}>
                {/* Un combobox et non un champ nu : c'est **l'orthographe exacte** qui
                    décide de la démonstration affichée pendant l'effort, et ni le modèle
                    ni l'utilisateur n'ont moyen de la deviner. La liste se réduit à chaque
                    frappe, et choisir une ligne écrit le nom du catalogue tel quel.

                    Le champ **reste libre** : un nom hors liste s'enregistre, la séance
                    tourne, elle perd seulement son illustration. Ces suggestions ne sont
                    pas des valeurs autorisées. */}
                <Combobox
                  label={`Exercice ${String(index + 1)}`}
                  placeholder="push-up"
                  value={line.name}
                  options={suggestions}
                  hint="Les noms du catalogue sont en anglais — cherche « push up », « plank »"
                  onChange={(name) => {
                    edit(index, { name }, 'name');
                    setSearch(name);
                  }}
                  onSelect={(option) => {
                    // Le groupe vient du catalogue, jamais deviné depuis le nom : un
                    // exercice inconnu laisse le sélecteur où il est.
                    const group = groupOf(option.value);
                    edit(
                      index,
                      group === null
                        ? { name: option.value }
                        : { name: option.value, muscle_group: group },
                      'name',
                    );
                  }}
                />
                {/* Ce que le nom vaut dans Cadence, dit sans jugement : un nom hors
                    catalogue reste valide et la séance tourne — elle n'affiche
                    simplement pas de démonstration. Le taire promettrait une image qui
                    n'arrivera pas ; l'écarter coûterait l'exercice.

                    `load` et non `recover` : ce n'est pas une erreur. Le peindre en rouge
                    ferait croire à un refus, et on corrigerait ce qui n'a rien de faux. */}
                {!proposal.exercises[index]?.illustrated &&
                  touched[key(index, 'name')] !== true && (
                    <Badge tone="load">sans démonstration</Badge>
                  )}
              </div>

              <div className={styles.composeRow}>
                <label className={styles.composeLabel} htmlFor={`group-${String(index)}`}>
                  Groupe musculaire
                </label>
                <select
                  id={`group-${String(index)}`}
                  className={styles.composeSelect}
                  value={line.muscle_group}
                  onChange={(event) => {
                    edit(index, { muscle_group: event.target.value }, 'group');
                  }}
                >
                  {(groups ?? []).map((group) => (
                    <option key={group} value={group}>
                      {group}
                    </option>
                  ))}
                </select>
              </div>

              <div className={styles.composeRow}>
                <Segmented
                  label="Durée ou répétitions"
                  value={line.mode}
                  options={MODES}
                  onChange={(mode) => {
                    edit(index, { mode }, 'mode');
                  }}
                />
              </div>

              {/* Le 4ᵉ champ du lien : ce que Cadence affichera sous le nom pendant
                  l'effort (`llms.txt` §1). La charge, elle, s'y joint toute seule côté
                  serveur — on ne la retape pas ici, sinon elle cesserait de suivre. */}
              <div className={styles.composeRow}>
                <Field
                  label="Note pendant l’effort"
                  value={line.note}
                  maxLength={60}
                  onChange={(event) => {
                    edit(index, { note: event.target.value }, 'note');
                  }}
                  placeholder="genoux au sol, tempo lent…"
                />
              </div>

              <div className={styles.composePair}>
                <Stepper
                  label={line.mode === 'time' ? 'Secondes' : 'Répétitions'}
                  value={line.value}
                  step={line.mode === 'time' ? 5 : 1}
                  proposed={proposed(index, 'value')}
                  onChange={(value) => {
                    edit(index, { value }, 'value');
                  }}
                />
                <Stepper
                  label="Repos (s)"
                  value={line.rest}
                  step={5}
                  proposed={proposed(index, 'rest')}
                  onChange={(value) => {
                    edit(index, { rest: value }, 'rest');
                  }}
                />
              </div>

              <div className={styles.composeAction}>
                <Button
                  variant="quiet"
                  onClick={() => {
                    setLines((current) => current.filter((_line, position) => position !== index));
                  }}
                >
                  Retirer cet exercice
                </Button>
              </div>
            </Card>
          ))}

          {/* Ce qui a été écarté à la relecture. Le taire laisserait croire que le modèle
              n'a proposé que cela, et rendrait incompréhensible une séance à deux
              exercices quand on en attendait six. */}
          {proposal.dropped.length > 0 && (
            <Card>
              <span className={styles.composeLabel}>
                {proposal.dropped.length} {plural(proposal.dropped.length, 'exercice')} écarté
                {proposal.dropped.length > 1 ? 's' : ''} à la relecture
              </span>
              <ul className={styles.composeBasis}>
                {proposal.dropped.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </Card>
          )}

          <Card>
            <div className={styles.composeAction}>
              <Button
                variant="primary"
                busy={save.isPending}
                disabled={payload === null}
                onClick={() => {
                  if (payload !== null) save.mutate(payload);
                }}
              >
                Enregistrer la séance
              </Button>
            </div>
            {/* L'appui est le seul moment où quelque chose est écrit, et l'écran le dit :
                c'est ce qui rend l'ajustement sans risque. */}
            <p className={styles.composeNote}>
              {payload === null
                ? 'Il manque un nom, un nombre de rounds, ou une valeur sur un exercice.'
                : 'Rien n’a encore été écrit. C’est cet appui qui enregistre.'}
            </p>
          </Card>
        </>
      )}
    </div>
  );
}
