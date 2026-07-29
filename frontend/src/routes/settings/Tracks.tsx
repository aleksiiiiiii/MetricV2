import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { Badge, Button, Card, Empty, Field, Rule } from '@/components/ui';
import {
  heatmapApi,
  type Track,
  type TrackImpact,
  type TrackPayload,
  type TracksView,
} from '@/features/heatmap/api';
import { ApiError } from '@/lib/api';
import { isoDay, shortDate } from '@/lib/format';
import { CROSS_CUTTING, keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from './Tracks.module.css';

/**
 * Réglage des pistes d'assiduité (`L11-10`, `L11-11`, `HEAT-18` → `HEAT-22`).
 *
 * ## L'asymétrie que cet écran doit rendre visible
 *
 * Une **cadence** est un engagement daté : la changer ne vaut que pour l'avenir
 * (`HEAT-14`). Un **seuil** est une définition : le changer rejuge tout l'historique
 * (`HEAT-20`). L'utilisateur n'a pas à connaître cette règle — il en reçoit le compte
 * rendu, et pour le second cas il le reçoit **avant** de valider.
 *
 * C'est la décision **D4**, et c'est la raison d'être du panneau de confirmation :
 * « 34 journées passeraient de validée à manquée » est une phrase qui fait réfléchir,
 * « ta grille va changer » n'en est pas une. Le compte vient du serveur, qui évalue la
 * grille deux fois et compare ; le recompter ici supposerait de réimplémenter la machine
 * à états, ce que `HEAT-30` interdit.
 *
 * ## Ce qui n'est pas codé ici
 *
 * Le **catalogue des sources** est servi par le serveur (`HEAT-02`). Une liste recopiée
 * dans ce fichier cesserait de décrire l'API au premier ajout, et proposerait une source
 * qui n'existe pas — ou tairait celle qui vient d'apparaître.
 */

/** Formes de cadence proposées à la saisie. Le serveur reste seul juge de leur validité. */
const CADENCE_KINDS = [
  { value: 'daily', label: 'Tous les jours' },
  { value: 'per_week', label: 'N fois par semaine' },
  { value: 'window', label: 'N fois par fenêtre glissante' },
  { value: 'conditional', label: 'Les jours d’entraînement' },
  { value: 'none', label: 'Sans attente (descriptive)' },
] as const;

type CadenceKind = (typeof CADENCE_KINDS)[number]['value'];

const ACCENT_LABEL: Record<string, string> = {
  signal: 'Mesure',
  effort: 'Effort',
  load: 'Charge',
  recover: 'Récupération',
};

interface Draft {
  label: string;
  source: string;
  filter: string;
  threshold: string;
  levels: string;
  binary: boolean;
  accent: string;
  active: boolean;
  kind: CadenceKind;
  count: string;
  windowDays: string;
}

/**
 * Compose la forme sérialisée attendue par l'API.
 *
 * Ce n'est **pas** un calcul métier : on assemble une chaîne de saisie, on n'interprète
 * aucune cadence. Le serveur la relit, la valide et la renvoie normalisée — et c'est lui
 * qui en formule le libellé français (`HEAT-30`).
 */
function serializeCadence(draft: Draft): string {
  switch (draft.kind) {
    case 'per_week':
      return `per_week:count=${draft.count || '1'}`;
    case 'window':
      return `window:min_count=${draft.count || '1'};window_days=${draft.windowDays || '2'}`;
    case 'conditional':
      return 'conditional:trigger=workout';
    case 'none':
      return 'none';
    default:
      return 'daily';
  }
}

function toDraft(track: Track): Draft {
  const kind = CADENCE_KINDS.find((item) => item.value === track.cadence.type)?.value ?? 'daily';

  return {
    label: track.label,
    source: track.source,
    filter: track.filter,
    threshold: String(track.validation_threshold),
    levels: track.levels.join(', '),
    binary: track.binary,
    accent: track.accent,
    active: track.active,
    kind,
    count: String(track.cadence.params.count ?? track.cadence.params.min_count ?? 1),
    windowDays: String(track.cadence.params.window_days ?? 2),
  };
}

function emptyDraft(source: string): Draft {
  return {
    label: '',
    source,
    filter: '',
    threshold: '1',
    levels: '',
    binary: false,
    accent: 'signal',
    active: true,
    kind: 'daily',
    count: '2',
    windowDays: '2',
  };
}

function toPayload(draft: Draft): TrackPayload {
  return {
    label: draft.label.trim(),
    source: draft.source,
    filter: draft.filter.trim(),
    // Le serveur porte les bornes de vraisemblance (`API-06`) : on transmet et on
    // affiche son refus, on n'en redéclare aucune.
    validation_threshold: Number.parseFloat(draft.threshold.replace(',', '.')) || 0,
    levels: draft.binary
      ? []
      : draft.levels
          .split(',')
          .map((chunk) => Number.parseFloat(chunk.trim().replace(',', '.')))
          .filter((value) => Number.isFinite(value)),
    binary: draft.binary,
    accent: draft.accent,
    cadence: serializeCadence(draft),
    active: draft.active,
  };
}

function TrackForm({
  draft,
  sources,
  accents,
  refusal,
  onChange,
}: {
  draft: Draft;
  sources: TracksView['sources'];
  accents: string[];
  refusal: ApiError | null;
  onChange: (next: Draft) => void;
}) {
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    onChange({ ...draft, [key]: value });
  };

  const source = sources.find((item) => item.key === draft.source);

  return (
    <div className={styles.form}>
      <Field
        label="Nom de la piste"
        value={draft.label}
        error={refusal?.messageFor('label')}
        onChange={(event) => {
          set('label', event.target.value);
        }}
      />

      <label className={styles.select}>
        <span>Source</span>
        <select
          value={draft.source}
          onChange={(event) => {
            set('source', event.target.value);
          }}
        >
          {sources.map((item) => (
            <option key={item.key} value={item.key}>
              {item.label}
            </option>
          ))}
        </select>
      </label>

      {/* Le catalogue dit lui-même si la source prend un filtre, et ce qu'il désigne :
          l'écran n'a pas à savoir quelle source attend quoi (`HEAT-02`). */}
      {source?.filter_label != null && (
        <Field
          label={source.filter_label}
          value={draft.filter}
          hint="Plusieurs valeurs séparées par des points-virgules"
          error={refusal?.messageFor('filter')}
          onChange={(event) => {
            set('filter', event.target.value);
          }}
        />
      )}

      <Field
        label={`Seuil de validation (${source?.unit ?? ''})`}
        inputMode="decimal"
        value={draft.threshold}
        hint="Au-delà, la journée est validée"
        error={refusal?.messageFor('validation_threshold')}
        onChange={(event) => {
          set('threshold', event.target.value);
        }}
      />

      <label className={styles.check}>
        <input
          type="checkbox"
          checked={draft.binary}
          onChange={(event) => {
            set('binary', event.target.checked);
          }}
        />
        {/* `HEAT-16` : une prise est une prise. Le gradient n'a de sens que pour une
            grandeur qui se cumule. */}
        <span>Un seul niveau — fait ou pas fait</span>
      </label>

      {!draft.binary && (
        <Field
          label="Seuils d’intensité"
          value={draft.levels}
          hint="Quatre bornes croissantes, séparées par des virgules — elles colorent le vert, elles ne décident pas de la validation"
          error={refusal?.messageFor('levels')}
          onChange={(event) => {
            set('levels', event.target.value);
          }}
        />
      )}

      <label className={styles.select}>
        <span>Cadence</span>
        <select
          value={draft.kind}
          onChange={(event) => {
            set('kind', event.target.value as CadenceKind);
          }}
        >
          {CADENCE_KINDS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </label>

      {(draft.kind === 'per_week' || draft.kind === 'window') && (
        <div className={styles.pair}>
          <Field
            label={draft.kind === 'per_week' ? 'Fois par semaine' : 'Fois par fenêtre'}
            inputMode="numeric"
            value={draft.count}
            error={refusal?.messageFor('cadence')}
            onChange={(event) => {
              set('count', event.target.value);
            }}
          />
          {draft.kind === 'window' && (
            <Field
              label="Jours de la fenêtre"
              inputMode="numeric"
              value={draft.windowDays}
              onChange={(event) => {
                set('windowDays', event.target.value);
              }}
            />
          )}
        </div>
      )}

      <label className={styles.select}>
        <span>Couleur</span>
        <select
          value={draft.accent}
          onChange={(event) => {
            set('accent', event.target.value);
          }}
        >
          {accents.map((accent) => (
            <option key={accent} value={accent}>
              {ACCENT_LABEL[accent] ?? accent}
            </option>
          ))}
        </select>
      </label>

      <label className={styles.check}>
        <input
          type="checkbox"
          checked={draft.active}
          onChange={(event) => {
            set('active', event.target.checked);
          }}
        />
        {/* `HEAT-21` : désactiver conserve l'historique, supprimer efface la lecture. */}
        <span>Afficher cette piste</span>
      </label>
    </div>
  );
}

/**
 * Panneau de confirmation d'un recalcul rétroactif (`HEAT-20`, décision **D4**).
 *
 * Il ne s'affiche que lorsqu'il a quelque chose à dire. Le faire apparaître à chaque
 * enregistrement le rendrait invisible en une semaine — et la fois où il compte
 * vraiment, personne ne le lirait.
 */
function ImpactPanel({
  impact,
  busy,
  onConfirm,
  onCancel,
}: {
  impact: TrackImpact;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className={styles.impact} role="alertdialog" aria-label="Recalcul de l’historique">
      <p className="eyebrow">Cette modification rejuge le passé</p>

      <ul className={styles.impactList}>
        {impact.warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>

      <p className={styles.impactRange}>
        Sur la plage du {shortDate(impact.range.from)} au {shortDate(impact.range.to)}.
      </p>

      <div className="row" style={{ marginTop: 14 }}>
        <Button variant="primary" busy={busy} onClick={onConfirm}>
          Appliquer quand même
        </Button>
        <Button variant="quiet" onClick={onCancel}>
          Annuler
        </Button>
      </div>
    </div>
  );
}

function TrackRow({
  track,
  highlighted,
  onEdit,
  editing,
}: {
  track: Track;
  highlighted: boolean;
  editing: boolean;
  onEdit: () => void;
}) {
  return (
    <div className="spread">
      <div>
        <h3 className={styles.rowName}>
          {track.label}
          {highlighted && <Badge tone="signal">mise en avant</Badge>}
          {!track.active && <Badge tone="load">masquée</Badge>}
        </h3>
        <p className={styles.rowMeta}>
          {track.source_label}
          {track.filter !== '' && ` · ${track.filter}`} · {track.cadence.label}
        </p>
      </div>
      <Button variant="quiet" onClick={onEdit}>
        {editing ? 'Replier' : 'Modifier'}
      </Button>
    </div>
  );
}

export function Tracks() {
  const client = useQueryClient();
  const { notify } = useToast();

  const { data, isPending, error } = useQuery({
    queryKey: keys.heatmap.tracks(),
    queryFn: heatmapApi.tracks,
  });

  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [creating, setCreating] = useState<Draft | null>(null);
  const [impact, setImpact] = useState<TrackImpact | null>(null);
  const [refusal, setRefusal] = useState<ApiError | null>(null);
  const [off, setOff] = useState({ track: '', from: '', to: '', reason: '' });

  function refresh() {
    void client.invalidateQueries({ queryKey: keys.heatmap.all() });
    for (const key of CROSS_CUTTING) void client.invalidateQueries({ queryKey: key });
    void client.invalidateQueries({ queryKey: keys.settings.all() });
  }

  function fail(caught: unknown, fallback: string) {
    setRefusal(caught instanceof ApiError ? caught : null);
    notify(caught instanceof ApiError ? caught.message : fallback, 'recover');
  }

  /** Simulation d'abord (**D4**) : on ne valide rien avant d'avoir dit ce que ça coûte. */
  const simulate = useMutation({
    mutationFn: ({ trackId, payload }: { trackId: string; payload: TrackPayload }) =>
      heatmapApi.preview(trackId, payload),
    onError: (caught: unknown) => {
      fail(caught, 'Simulation impossible.');
    },
  });

  const save = useMutation({
    mutationFn: ({ track, payload }: { track: Track; payload: TrackPayload }) =>
      heatmapApi.update(track.track_id, payload, track.token),

    onSuccess: (saved) => {
      refresh();
      setEditing(null);
      setDraft(null);
      setImpact(null);
      setRefusal(null);
      // Les avertissements viennent du serveur, en français, et s'affichent tels quels.
      notify(saved.warnings[0] ?? 'Piste enregistrée.', 'effort');
    },

    onError: (caught: unknown) => {
      if (caught instanceof ApiError && caught.code === 'conflict') {
        // La garde a parlé : repartir de ce que le fichier vaut vraiment (`STO-05`).
        void client.invalidateQueries({ queryKey: keys.heatmap.tracks() });
        setEditing(null);
        setDraft(null);
      }
      setImpact(null);
      fail(caught, 'Enregistrement impossible.');
    },
  });

  const create = useMutation({
    mutationFn: (payload: TrackPayload) => heatmapApi.create(payload),
    onSuccess: () => {
      refresh();
      setCreating(null);
      setRefusal(null);
      notify('Piste créée. Son historique commence aujourd’hui.', 'effort');
    },
    onError: (caught: unknown) => {
      fail(caught, 'Création impossible.');
    },
  });

  const remove = useMutation({
    mutationFn: (track: Track) => heatmapApi.remove(track.track_id, track.token),
    onSuccess: () => {
      refresh();
      setEditing(null);
      notify('Piste supprimée. Aucune donnée de saisie n’a été touchée.', 'effort');
    },
    onError: (caught: unknown) => {
      fail(caught, 'Suppression impossible.');
    },
  });

  const reorder = useMutation({
    mutationFn: (trackIds: string[]) => heatmapApi.reorder(trackIds),
    onSuccess: refresh,
    onError: (caught: unknown) => {
      fail(caught, 'Réordonnancement impossible.');
    },
  });

  const highlight = useMutation({
    mutationFn: (trackId: string) => heatmapApi.highlight(trackId),
    onSuccess: refresh,
    onError: (caught: unknown) => {
      fail(caught, 'Mise en avant impossible.');
    },
  });

  const neutralise = useMutation({
    mutationFn: () =>
      heatmapApi.neutralise({
        track_id: off.track,
        date_from: off.from,
        date_to: off.to,
        reason: off.reason,
      }),
    onSuccess: () => {
      refresh();
      setOff({ track: '', from: '', to: '', reason: '' });
      setRefusal(null);
      notify(
        'Plage neutralisée. Ces jours ne comptent ni comme réussite ni comme échec.',
        'effort',
      );
    },
    onError: (caught: unknown) => {
      fail(caught, 'Neutralisation impossible.');
    },
  });

  const cancelOff = useMutation({
    mutationFn: ({ offId, token }: { offId: string; token: string }) =>
      heatmapApi.cancelNeutralisation(offId, token),
    onSuccess: refresh,
    onError: (caught: unknown) => {
      fail(caught, 'Annulation impossible.');
    },
  });

  if (isPending) return <p className={styles.muted}>chargement des pistes…</p>;

  if (error || !data) {
    return (
      <Empty title="Pistes indisponibles">
        {error instanceof Error ? error.message : 'Le serveur n’a pas répondu.'}
      </Empty>
    );
  }

  const order = data.tracks.map((track) => track.track_id);

  function move(trackId: string, delta: number) {
    const from = order.indexOf(trackId);
    const to = from + delta;
    if (to < 0 || to >= order.length) return;

    const next = [...order];
    const [moved] = next.splice(from, 1);
    if (moved === undefined) return;
    next.splice(to, 0, moved);
    reorder.mutate(next);
  }

  function submit(track: Track) {
    if (!draft) return;
    const payload = toPayload(draft);

    // On demande d'abord au serveur ce que ça ferait. S'il répond « rien de rétroactif »,
    // on enregistre sans déranger.
    simulate.mutate(
      { trackId: track.track_id, payload },
      {
        onSuccess: (result) => {
          if (result.retroactive && (result.changed_days > 0 || result.restyled > 0)) {
            setImpact(result);
            return;
          }
          save.mutate({ track, payload });
        },
      },
    );
  }

  const editedTrack = data.tracks.find((track) => track.track_id === editing) ?? null;

  return (
    <>
      <Rule>Pistes d’assiduité</Rule>

      <p className="lede" style={{ marginTop: 14, marginBottom: 20 }}>
        Une piste décrit un engagement : une source, un seuil qui dit ce que « validé » signifie, et
        une cadence qui dit à quelle fréquence c’est attendu. Changer la cadence ne vaut que pour
        l’avenir ; changer un seuil rejuge tout l’historique, et l’ampleur t’en est annoncée avant
        que tu valides.
      </p>

      {refusal !== null && refusal.fields.length === 0 && (
        <p className={styles.error} role="alert">
          {refusal.message}
        </p>
      )}

      <div className={styles.list}>
        {data.tracks.map((track, index) => (
          <Card key={track.track_id}>
            <TrackRow
              track={track}
              highlighted={data.highlight === track.track_id}
              editing={editing === track.track_id}
              onEdit={() => {
                setImpact(null);
                setRefusal(null);
                if (editing === track.track_id) {
                  setEditing(null);
                  setDraft(null);
                } else {
                  setEditing(track.track_id);
                  setDraft(toDraft(track));
                }
              }}
            />

            {editing === track.track_id && draft !== null && (
              <>
                <TrackForm
                  draft={draft}
                  sources={data.sources}
                  accents={data.accents}
                  refusal={refusal}
                  onChange={setDraft}
                />

                {impact !== null ? (
                  <ImpactPanel
                    impact={impact}
                    busy={save.isPending}
                    onConfirm={() => {
                      save.mutate({ track, payload: toPayload(draft) });
                    }}
                    onCancel={() => {
                      setImpact(null);
                    }}
                  />
                ) : (
                  <div className={styles.actions}>
                    <Button
                      variant="primary"
                      busy={simulate.isPending || save.isPending}
                      onClick={() => {
                        submit(track);
                      }}
                    >
                      Enregistrer
                    </Button>
                    <Button
                      onClick={() => {
                        move(track.track_id, -1);
                      }}
                      disabled={index === 0}
                    >
                      Monter
                    </Button>
                    <Button
                      onClick={() => {
                        move(track.track_id, 1);
                      }}
                      disabled={index === data.tracks.length - 1}
                    >
                      Descendre
                    </Button>
                    <Button
                      onClick={() => {
                        highlight.mutate(track.track_id);
                      }}
                      disabled={data.highlight === track.track_id}
                    >
                      Mettre en avant
                    </Button>
                    <Button
                      onClick={() => {
                        remove.mutate(track);
                      }}
                    >
                      Supprimer
                    </Button>
                  </div>
                )}

                <p className={styles.note}>
                  Supprimer une piste n’efface aucune mesure : les séries, les kilomètres et les
                  prises restent dans leurs fichiers. Pour garder l’historique sans afficher la
                  grille, décoche « Afficher cette piste ».
                </p>
              </>
            )}
          </Card>
        ))}
      </div>

      <div className={styles.actions}>
        {creating === null ? (
          <Button
            onClick={() => {
              setRefusal(null);
              setCreating(emptyDraft(data.sources[0]?.key ?? ''));
            }}
          >
            Ajouter une piste
          </Button>
        ) : (
          <Button
            variant="quiet"
            onClick={() => {
              setCreating(null);
            }}
          >
            Annuler
          </Button>
        )}
      </div>

      {creating !== null && (
        <Card className={styles.creator}>
          <p className="eyebrow">Nouvelle piste</p>
          <TrackForm
            draft={creating}
            sources={data.sources}
            accents={data.accents}
            refusal={refusal}
            onChange={setCreating}
          />
          <div className={styles.actions}>
            <Button
              variant="primary"
              busy={create.isPending}
              onClick={() => {
                create.mutate(toPayload(creating));
              }}
            >
              Créer
            </Button>
          </div>
          <p className={styles.note}>
            {/* `HEAT-07` : une piste ne produit aucun état avant sa création. */}
            L’historique de cette piste commencera aujourd’hui. Les mois précédents resteront vides
            — ils ne seront pas comptés comme manqués.
          </p>
        </Card>
      )}

      <Rule>Jours neutralisés</Rule>

      <p className="lede" style={{ marginTop: 14, marginBottom: 20 }}>
        Maladie, voyage, deload : ces jours ne comptent ni comme réussite ni comme échec. Une grippe
        ne casse pas une série de quatre-vingt-dix jours.
      </p>

      <Card>
        <div className={styles.form}>
          <label className={styles.select}>
            <span>Piste</span>
            <select
              value={off.track}
              onChange={(event) => {
                setOff({ ...off, track: event.target.value });
              }}
            >
              <option value="">Toutes les pistes</option>
              {data.tracks.map((track) => (
                <option key={track.track_id} value={track.track_id}>
                  {track.label}
                </option>
              ))}
            </select>
          </label>

          <div className={styles.pair}>
            <Field
              label="Du"
              type="date"
              max={isoDay(new Date())}
              value={off.from}
              error={refusal?.messageFor('date_from')}
              onChange={(event) => {
                setOff({ ...off, from: event.target.value });
              }}
            />
            <Field
              label="Au"
              type="date"
              max={isoDay(new Date())}
              value={off.to}
              error={refusal?.messageFor('date_to')}
              onChange={(event) => {
                setOff({ ...off, to: event.target.value });
              }}
            />
          </div>

          <Field
            label="Raison"
            value={off.reason}
            hint="Notée dans le fichier, pour se souvenir dans six mois"
            onChange={(event) => {
              setOff({ ...off, reason: event.target.value });
            }}
          />
        </div>

        <div className={styles.actions}>
          <Button
            variant="primary"
            busy={neutralise.isPending}
            disabled={off.from === '' || off.to === ''}
            onClick={() => {
              neutralise.mutate();
            }}
          >
            Neutraliser
          </Button>
        </div>
      </Card>

      {data.off_days.length > 0 && (
        <div className={styles.list}>
          {data.off_days.map((entry) => (
            <Card key={entry.off_id}>
              <div className="spread">
                <div>
                  <div className={styles.rowName}>
                    {shortDate(entry.date_from)} → {shortDate(entry.date_to)}
                    <Badge tone="load" mono>
                      {entry.days} j
                    </Badge>
                  </div>
                  <p className={styles.rowMeta}>
                    {entry.track_id === ''
                      ? 'toutes les pistes'
                      : (data.tracks.find((track) => track.track_id === entry.track_id)?.label ??
                        entry.track_id)}
                    {entry.reason !== '' && ` · ${entry.reason}`}
                  </p>
                </div>
                {/* « Rétablir » et non « Annuler » : ces jours redeviennent jugeables,
                    et le mot doit dire ce qui arrive à la grille — pas ce qui arrive au
                    formulaire. */}
                <Button
                  variant="quiet"
                  onClick={() => {
                    cancelOff.mutate({ offId: entry.off_id, token: entry.token });
                  }}
                >
                  Rétablir
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {editedTrack === null && data.tracks.length === 0 && (
        <Empty title="Aucune piste">
          Ouvre l’écran Assiduité une première fois : les neuf pistes par défaut y sont amorcées à
          partir de ton propre historique.
        </Empty>
      )}
    </>
  );
}
