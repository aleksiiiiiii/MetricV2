import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import {
  AiBlock,
  Badge,
  Button,
  Card,
  Chip,
  ChipStrip,
  Empty,
  Field,
  Rule,
  Segmented,
  Stepper,
} from '@/components/ui';
import { useAiStatus } from '@/features/ai/useAiStatus';
import {
  planningApi,
  type DayCell,
  type MonthView,
  type PlanFormValues,
  type PlanKind,
  type PlannedSession,
  type Proposal,
  type ProposedSession,
} from '@/features/planning/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { hoursMinutes, longDate, percent, plural, shortDate } from '@/lib/format';
import { CROSS_CUTTING, keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from './Planning.module.css';

/**
 * Écran Planning (`L13-07`).
 *
 * ## Ce que l'écran ne fait pas
 *
 * Il ne compose pas son calendrier. Le mois arrive **découpé en semaines complètes**,
 * débordements compris, avec le jour courant tel que le serveur le voit. Recalculer le
 * premier lundi ici serait une seconde implémentation de « la semaine commence le lundi »,
 * et `toISOString().slice(0,10)` décalerait la journée d'un fuseau (`HEAT-32`).
 *
 * Il ne calcule pas non plus le taux de respect : `PLAN-06` est du ressort du serveur,
 * comme les deux autres taux du projet.
 *
 * ## Mobile d'abord, et c'est le cas le plus dur du projet
 *
 * Sept colonnes dans 390 px laissent moins de cinquante pixels par jour. Deux
 * conséquences assumées :
 *
 * * **une case ne porte pas de texte** — seulement le quantième et deux marques, prévu et
 *   effectué. Y écrire « Haut du corps » donnerait trois pixels par lettre ;
 * * **le détail vit sous la grille**, dans le panneau du jour sélectionné. La grille
 *   répond à « quand », le panneau à « quoi ». C'est ce découpage qui permet de garder
 *   chaque case au-dessus du plancher de 44 px plutôt que d'entasser.
 */

const KIND_LABELS: Record<PlanKind, string> = {
  course: 'Course',
  muscu: 'Muscu',
  autre: 'Autre',
};

const KIND_OPTIONS = [
  { value: 'muscu' as const, label: 'Muscu' },
  { value: 'course' as const, label: 'Course' },
  { value: 'autre' as const, label: 'Autre' },
];

const WEEKDAYS = ['L', 'M', 'M', 'J', 'V', 'S', 'D'];
const WEEKDAY_NAMES = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche'];

const EMPTY_FORM: PlanFormValues = {
  date: '',
  time: null,
  kind: 'muscu',
  title: '',
  duration_min: '60',
  note: '',
};

/**
 * Mois affiché, `AAAA-MM`, décalé de `offset` mois.
 *
 * Le seul calcul de date que l'écran s'autorise, et il ne porte sur aucune donnée : il
 * choisit quelle page demander au serveur. Construit sur des nombres et non sur un `Date`
 * pour éviter qu'un 31 mai « + 1 mois » atterrisse en juillet.
 */
function shiftMonth(month: string, offset: number): string {
  const [year, index] = month.split('-').map(Number);
  const total = (year ?? 0) * 12 + (index ?? 1) - 1 + offset;
  return `${String(Math.floor(total / 12))}-${String((total % 12) + 1).padStart(2, '0')}`;
}

function monthLabel(month: string): string {
  return new Date(`${month}-01T12:00:00`).toLocaleDateString('fr-FR', {
    month: 'long',
    year: 'numeric',
  });
}

function sessionLine(session: PlannedSession | ProposedSession): string {
  const clock = session.time ?? 'sans heure';
  return `${clock} · ${KIND_LABELS[session.kind]} · ${hoursMinutes(session.duration_min)}`;
}

/** Ce qu'une proposition devient une fois adoptée — la même charge utile qu'une saisie. */
function toFormValues(session: ProposedSession): PlanFormValues {
  return {
    date: session.date,
    time: session.time,
    kind: session.kind,
    title: session.title,
    duration_min: String(session.duration_min),
    note: session.note,
  };
}

function useInvalidatePlanning() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: keys.planning.all() });
    for (const key of CROSS_CUTTING) void client.invalidateQueries({ queryKey: key });
  };
}

// ── Grille du mois (`PLAN-01`) ────────────────────────

function DayButton({
  cell,
  today,
  selected,
  onSelect,
}: {
  cell: DayCell;
  today: string;
  selected: boolean;
  onSelect: (day: string) => void;
}) {
  const quantieme = Number(cell.date.slice(8));
  const planned = cell.planned.length;
  const done = cell.done.length;

  // Le nom accessible dit ce que la case montre : deux pastilles de six pixels ne se
  // lisent pas à la synthèse vocale, et « 12 » tout seul ne dirait rien.
  const label = [
    longDate(`${cell.date}T12:00:00`),
    planned > 0 ? `${String(planned)} ${plural(planned, 'prévue')}` : null,
    done > 0 ? `${String(done)} ${plural(done, 'effectuée')}` : null,
  ]
    .filter(Boolean)
    .join(', ');

  return (
    <button
      type="button"
      className={cx(
        styles.day,
        !cell.in_month && styles.dayOutside,
        cell.date === today && styles.dayToday,
        selected && styles.daySelected,
      )}
      aria-pressed={selected}
      aria-label={label}
      onClick={() => {
        onSelect(cell.date);
      }}
    >
      <span className={styles.dayNumber}>{quantieme}</span>
      <span className={styles.marks} aria-hidden="true">
        {planned > 0 && <span className={styles.markPlanned} />}
        {done > 0 && <span className={styles.markDone} />}
      </span>
    </button>
  );
}

function MonthGrid({
  view,
  selected,
  onSelect,
}: {
  view: MonthView;
  selected: string;
  onSelect: (day: string) => void;
}) {
  return (
    <div
      className={styles.grid}
      role="grid"
      aria-label={`Calendrier de ${monthLabel(view.month.slice(0, 7))}`}
    >
      <div className={styles.weekdays} role="row">
        {WEEKDAYS.map((letter, index) => (
          <span key={WEEKDAY_NAMES[index]} role="columnheader" aria-label={WEEKDAY_NAMES[index]}>
            {letter}
          </span>
        ))}
      </div>

      <div className={styles.days}>
        {view.days.map((cell) => (
          <DayButton
            key={cell.date}
            cell={cell}
            today={view.today}
            selected={cell.date === selected}
            onSelect={onSelect}
          />
        ))}
      </div>

      <p className={styles.legend}>
        <span className={styles.markPlanned} aria-hidden="true" /> prévu
        <span className={styles.markDone} aria-hidden="true" /> effectué
      </p>
    </div>
  );
}

// ── Panneau du jour (`PLAN-01`, `PLAN-02`) ────────────

function DayPanel({
  cell,
  onEdit,
  onPlan,
}: {
  cell: DayCell | undefined;
  onEdit: (session: PlannedSession) => void;
  onPlan: () => void;
}) {
  const invalidate = useInvalidatePlanning();
  const { notify } = useToast();
  const [armed, setArmed] = useState<number | null>(null);

  const remove = useMutation({
    mutationFn: ({ id, token }: { id: number; token: string }) => planningApi.remove(id, token),
    onSuccess: () => {
      setArmed(null);
      invalidate();
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Suppression impossible.', 'recover');
    },
  });

  if (!cell) return null;

  const empty = cell.planned.length === 0 && cell.done.length === 0;

  return (
    <Card>
      <div className="spread">
        <h3>{longDate(`${cell.date}T12:00:00`)}</h3>
        <Button variant="primary" onClick={onPlan}>
          Planifier
        </Button>
      </div>

      {empty && (
        <Empty title="Rien ce jour-là">
          Une séance posée à l'avance est une séance qu'on ne discute plus le matin venu.
        </Empty>
      )}

      {cell.planned.length > 0 && (
        <ul className={styles.list}>
          {cell.planned.map((session) => (
            <li key={session.session_id} className={styles.item}>
              <div className={styles.itemBody}>
                <div className="spread">
                  <strong>{session.title}</strong>
                  {session.source === 'ai' && <Badge tone="signal">proposée</Badge>}
                </div>
                <span className={styles.meta}>{sessionLine(session)}</span>
                {session.note !== null && session.note !== '' && (
                  <span className={styles.note}>{session.note}</span>
                )}
              </div>

              <div className={styles.itemActions}>
                <Button
                  variant="quiet"
                  onClick={() => {
                    onEdit(session);
                  }}
                >
                  Modifier
                </Button>
                {/* Deux appuis pour détruire : le projet n'a pas d'annulation.
                    Le nom accessible désigne **quelle** séance — la même règle que
                    `SwipeRow`, et elle compte double ici où deux boutons « Retirer »
                    coexistent à l'écran pour deux gestes très différents. */}
                <Button
                  variant="quiet"
                  busy={remove.isPending}
                  aria-label={
                    armed === session.id
                      ? `Supprimer ${session.title} — confirmer`
                      : `Supprimer ${session.title} du planning`
                  }
                  onClick={() => {
                    if (armed !== session.id) {
                      setArmed(session.id);
                      return;
                    }
                    remove.mutate({ id: session.id, token: session.token });
                  }}
                >
                  {armed === session.id ? 'Confirmer ?' : 'Retirer'}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {cell.done.length > 0 && (
        <>
          <Rule>Effectué</Rule>
          <ul className={styles.list}>
            {cell.done.map((activity) => (
              <li key={`${activity.kind}-${String(activity.id)}`} className={styles.item}>
                <div className={styles.itemBody}>
                  <strong>{activity.label}</strong>
                  <span className={styles.meta}>{hoursMinutes(activity.duration_min)}</span>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

// ── Formulaire (`PLAN-02`) ────────────────────────────

function PlanForm({
  values,
  editing,
  onChange,
  onDone,
}: {
  values: PlanFormValues;
  editing: PlannedSession | null;
  onChange: (values: PlanFormValues) => void;
  onDone: () => void;
}) {
  const invalidate = useInvalidatePlanning();
  const { notify } = useToast();
  const [error, setError] = useState<ApiError | null>(null);

  const save = useMutation({
    mutationFn: (payload: PlanFormValues) =>
      editing
        ? planningApi.update(editing.id, editing.token, payload)
        : planningApi.create(payload),
    onSuccess: () => {
      setError(null);
      invalidate();
      onDone();
    },
    onError: (caught: unknown) => {
      if (caught instanceof ApiError) {
        setError(caught);
        notify(caught.message, 'recover');
        return;
      }
      notify('Enregistrement impossible.', 'recover');
    },
  });

  function set<K extends keyof PlanFormValues>(key: K, value: PlanFormValues[K]): void {
    onChange({ ...values, [key]: value });
  }

  return (
    <Card>
      <div className="spread">
        <h3>{editing ? 'Modifier la séance' : 'Planifier une séance'}</h3>
        <Button variant="quiet" onClick={onDone}>
          Fermer
        </Button>
      </div>

      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate(values);
        }}
      >
        <Field
          label="Date"
          type="date"
          value={values.date}
          error={error?.messageFor('date')}
          onChange={(event) => {
            set('date', event.target.value);
          }}
        />

        <Field
          label="Heure"
          type="time"
          value={values.time ?? ''}
          hint="Facultative — sans heure, la séance tient la journée entière."
          error={error?.messageFor('time')}
          onChange={(event) => {
            set('time', event.target.value || null);
          }}
        />

        <div className={styles.kinds}>
          <ChipStrip label="Nature de la séance">
            {KIND_OPTIONS.map((option) => (
              <Chip
                key={option.value}
                selected={values.kind === option.value}
                onClick={() => {
                  set('kind', option.value);
                }}
              >
                {option.label}
              </Chip>
            ))}
          </ChipStrip>
        </div>

        <Field
          label="Titre"
          value={values.title}
          placeholder="Haut du corps"
          error={error?.messageFor('title')}
          onChange={(event) => {
            set('title', event.target.value);
          }}
        />

        <Stepper
          label="Durée (min)"
          value={values.duration_min}
          step={15}
          min={5}
          max={300}
          error={error?.messageFor('duration_min')}
          onChange={(value) => {
            set('duration_min', value);
          }}
        />

        <Field
          label="Note"
          value={values.note ?? ''}
          placeholder="5×5, montée en charge"
          onChange={(event) => {
            set('note', event.target.value);
          }}
        />

        <Button type="submit" variant="primary" busy={save.isPending} className={styles.submit}>
          {editing ? 'Enregistrer' : 'Planifier'}
        </Button>
      </form>
    </Card>
  );
}

// ── Proposition assistée (`PLAN-03`, `PLAN-04`) ───────

function ProposalCard() {
  const invalidate = useInvalidatePlanning();
  const { notify } = useToast();
  const { enabled } = useAiStatus();

  const [weeks, setWeeks] = useState<'1' | '2'>('1');
  const [constraints, setConstraints] = useState('');
  const [objective, setObjective] = useState('');
  const [proposal, setProposal] = useState<Proposal | null>(null);
  // Les séances retirées à l'écran, par leur rang. Le serveur ne reçoit que ce qui reste.
  const [removed, setRemoved] = useState<Set<number>>(new Set());

  const ask = useMutation({
    mutationFn: () => planningApi.propose({ weeks: weeks === '2' ? 2 : 1, constraints, objective }),
    onSuccess: (result) => {
      setProposal(result);
      setRemoved(new Set());
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Proposition impossible.', 'recover');
    },
  });

  const adopt = useMutation({
    mutationFn: (sessions: ProposedSession[]) => planningApi.adopt(sessions.map(toFormValues)),
    onSuccess: (result) => {
      setProposal(null);
      setRemoved(new Set());
      invalidate();
      notify(
        `${String(result.created.length)} ${plural(result.created.length, 'séance')} ${plural(result.created.length, 'ajoutée')} au planning.`,
        'effort',
      );
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Adoption impossible.', 'recover');
    },
  });

  if (!enabled) return null;

  const kept = (proposal?.sessions ?? []).filter((_, index) => !removed.has(index));

  return (
    <Card>
      <div className="spread">
        <div>
          <h3>Proposer un planning</h3>
          <p className={styles.note}>
            À partir de ta fréquence réelle et des groupes délaissés. Rien n'est écrit tant que tu
            n'as pas adopté.
          </p>
        </div>
      </div>

      <div className={styles.form}>
        <Segmented
          label="Durée du planning"
          options={[
            { value: '1', label: 'Une semaine' },
            { value: '2', label: 'Deux semaines' },
          ]}
          value={weeks}
          onChange={setWeeks}
        />

        {/* Facultatif depuis le lot L14 : laissé vide, le serveur y met l'objectif actif
            de l'écran Objectif (`GOAL-01`). Rempli, il le remplace ponctuellement — et
            c'est tout ce qui reste de l'écart assumé du L13, où il fallait retaper son
            objectif à chaque proposition sous peine d'obtenir une semaine qui l'ignorait
            sans le dire. */}
        <Field
          label="Objectif, ponctuellement"
          value={objective}
          placeholder="cette semaine je prépare une course"
          hint="Facultatif — sans rien, l'objectif en cours est utilisé."
          onChange={(event) => {
            setObjective(event.target.value);
          }}
        />

        <Field
          label="Contraintes"
          value={constraints}
          placeholder="pas le mercredi, genou fragile"
          onChange={(event) => {
            setConstraints(event.target.value);
          }}
        />

        <Button
          variant="primary"
          busy={ask.isPending}
          className={styles.submit}
          onClick={() => {
            ask.mutate();
          }}
        >
          Proposer
        </Button>
      </div>

      {proposal && (
        <AiBlock
          tag="Proposition"
          actions={
            <>
              <Button
                variant="primary"
                busy={adopt.isPending}
                disabled={kept.length === 0}
                onClick={() => {
                  adopt.mutate(kept);
                }}
              >
                Adopter {kept.length > 0 ? `(${String(kept.length)})` : ''}
              </Button>
              <Button
                variant="quiet"
                onClick={() => {
                  setProposal(null);
                }}
              >
                Pas d&apos;accord
              </Button>
            </>
          }
        >
          <p>
            Du {shortDate(`${proposal.start}T12:00:00`)} au {shortDate(`${proposal.end}T12:00:00`)}
            {proposal.basis.length > 0 && <> — {proposal.basis.join(', ')}</>}.
          </p>

          <ul className={styles.proposed}>
            {proposal.sessions.map((session, index) => (
              <li
                key={`${session.date}-${session.kind}`}
                className={cx(styles.item, removed.has(index) && styles.itemDropped)}
              >
                <div className={styles.itemBody}>
                  <strong>
                    {longDate(`${session.date}T12:00:00`)} — {session.title}
                  </strong>
                  <span className={styles.meta}>{sessionLine(session)}</span>
                  {session.reason !== null && <span className={styles.note}>{session.reason}</span>}
                </div>

                {/* Le « Pas d'accord » du lot L12, appliqué à une liste : on retire une
                    séance sans renoncer aux autres. Réversible tant que rien n'est écrit. */}
                <Button
                  variant="quiet"
                  aria-label={`${removed.has(index) ? 'Remettre' : 'Retirer'} ${
                    session.title
                  } de la proposition`}
                  onClick={() => {
                    setRemoved((current) => {
                      const next = new Set(current);
                      if (next.has(index)) next.delete(index);
                      else next.add(index);
                      return next;
                    });
                  }}
                >
                  {removed.has(index) ? 'Remettre' : 'Retirer'}
                </Button>
              </li>
            ))}
          </ul>

          {proposal.dropped.length > 0 && (
            <p className={styles.dropped}>Écarté à la relecture : {proposal.dropped.join(' ')}</p>
          )}
        </AiBlock>
      )}
    </Card>
  );
}

// ── Abonnement iCal (`PLAN-05`) ───────────────────────

function SubscriptionCard() {
  const { notify } = useToast();
  const { data } = useQuery({
    queryKey: keys.planning.subscription(),
    queryFn: planningApi.subscription,
    staleTime: Infinity,
    retry: false,
  });

  if (!data) return null;

  return (
    <Card>
      <h3>Abonnement calendrier</h3>
      <p className={styles.note}>{data.message}</p>

      {data.url !== null && (
        <div className={styles.subscription}>
          <code className={styles.url}>{data.url}</code>
          <Button
            onClick={() => {
              void navigator.clipboard
                .writeText(data.url ?? '')
                .then(() => {
                  notify('Adresse copiée.', 'signal');
                })
                .catch(() => {
                  notify('Copie impossible — sélectionne l’adresse à la main.', 'recover');
                });
            }}
          >
            Copier l&apos;adresse
          </Button>
        </div>
      )}

      {/* Un lien reste un lien — c'est un téléchargement, pas une action d'application —
          mais il se touche comme un bouton : mesuré à 17 px de haut, il était la seule
          cible de l'écran sous le plancher de `--tap`. */}
      <a className={styles.download} href="/api/planning/export.ics" download>
        Télécharger le planning une fois
      </a>
      <p className={styles.note}>Un fichier figé, qui ne se met pas à jour tout seul.</p>
    </Card>
  );
}

// ── Écran ─────────────────────────────────────────────

export function Planning() {
  const [month, setMonth] = useState<string>(() => {
    // Amorçage seulement : dès la première réponse, c'est le serveur qui dit quel jour
    // on est. Ce mois-ci peut être faux d'un jour à la frontière d'un fuseau, jamais
    // d'un mois.
    const now = new Date();
    return `${String(now.getFullYear())}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [form, setForm] = useState<PlanFormValues | null>(null);
  const [editing, setEditing] = useState<PlannedSession | null>(null);

  const {
    data: view,
    isPending,
    error,
  } = useQuery({
    queryKey: keys.planning.month(month),
    queryFn: () => planningApi.month(month),
  });

  const { data: adherence } = useQuery({
    queryKey: keys.planning.adherence(),
    queryFn: () => planningApi.adherence(),
  });

  const day = useMemo(() => {
    if (!view) return undefined;
    const wanted = selected ?? view.today;
    return (
      view.days.find((cell) => cell.date === wanted) ?? view.days.find((cell) => cell.in_month)
    );
  }, [view, selected]);

  function openForm(values: Partial<PlanFormValues>, session: PlannedSession | null): void {
    setEditing(session);
    setForm({ ...EMPTY_FORM, date: day?.date ?? '', ...values });
  }

  return (
    <div className={cx('wrap', styles.screen)}>
      <header className={styles.head}>
        <div>
          <p className="eyebrow">Planning</p>
          <h2 className={styles.month}>{monthLabel(month)}</h2>
        </div>

        <div className={styles.nav}>
          <Button
            aria-label="Mois précédent"
            onClick={() => {
              setMonth((current) => shiftMonth(current, -1));
            }}
          >
            ←
          </Button>
          <Button
            onClick={() => {
              if (view) {
                setMonth(view.today.slice(0, 7));
                setSelected(view.today);
              }
            }}
          >
            Aujourd&apos;hui
          </Button>
          <Button
            aria-label="Mois suivant"
            onClick={() => {
              setMonth((current) => shiftMonth(current, 1));
            }}
          >
            →
          </Button>
        </div>
      </header>

      {isPending && <Card>Chargement du planning…</Card>}

      {error !== null && (
        <Card>
          <Empty title="Planning indisponible">
            {error instanceof ApiError ? error.message : 'Le serveur est injoignable.'}
          </Empty>
        </Card>
      )}

      {view && (
        <>
          {adherence && (
            <Card>
              <div className="spread">
                <h3>Respect du planning</h3>
                <Badge tone={(adherence.rate ?? 0) >= 0.7 ? 'effort' : 'signal'} mono>
                  {/* Rien de prévu n'est pas 0 % : c'est l'absence de taux. */}
                  {adherence.rate === null ? '—' : percent(adherence.rate)}
                </Badge>
              </div>

              {/* Trois chiffres compacts plutôt que trois tuiles `Stat` : mesurées dans
                  le navigateur, celles-ci repoussaient le calendrier — le sujet de
                  l'écran — au-delà du pli sur un iPhone. Même forme que les chiffres de
                  piste de l'écran Assiduité, qui pose le même problème. */}
              <div className={styles.stats}>
                <div className={styles.stat}>
                  <span className={styles.statKey}>Prévues</span>
                  <span className={styles.statValue}>{adherence.planned}</span>
                </div>
                <div className={styles.stat}>
                  <span className={styles.statKey}>Honorées</span>
                  <span className={styles.statValue}>{adherence.honoured}</span>
                </div>
                <div className={styles.stat}>
                  <span className={styles.statKey}>Fenêtre</span>
                  <span className={styles.statValue}>{adherence.weeks.length} sem.</span>
                </div>
              </div>

              {adherence.planned === 0 && (
                <p className={styles.note}>
                  Rien n&apos;a encore été planifié sur la période : le taux n&apos;a pas de sens
                  tant qu&apos;il n&apos;y a pas de rendez-vous à tenir.
                </p>
              )}
            </Card>
          )}

          <Card>
            <MonthGrid
              view={view}
              selected={selected ?? view.today}
              onSelect={(picked) => {
                setSelected(picked);
                setForm(null);
              }}
            />
          </Card>

          <DayPanel
            cell={day}
            onPlan={() => {
              openForm({ date: day?.date ?? view.today }, null);
            }}
            onEdit={(session) => {
              openForm(
                {
                  date: session.date,
                  time: session.time,
                  kind: session.kind,
                  title: session.title,
                  duration_min: String(session.duration_min),
                  note: session.note ?? '',
                },
                session,
              );
            }}
          />

          {form !== null && (
            <PlanForm
              values={form}
              editing={editing}
              onChange={setForm}
              onDone={() => {
                setForm(null);
                setEditing(null);
              }}
            />
          )}

          <ProposalCard />
          <SubscriptionCard />
        </>
      )}
    </div>
  );
}
