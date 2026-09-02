/**
 * Écran Activité — courses et séances.
 *
 * **Ce qu'on fait passe devant ce qu'on lit.** L'écran était un tableau de bord auquel on
 * avait ajouté un formulaire : trois sections de statistiques, puis le journal, puis la
 * saisie. Consigner une série entre deux exercices demandait de traverser l'écran. Le
 * journal est passé en tête, puis les statistiques ont quitté la page.
 *
 * **Ce qui reste ici tient dans un geste** : la séance ouverte, l'historique pour en
 * rouvrir une autre, et l'import d'une capture. Le catalogue et les chiffres ont chacun
 * leur adresse — `/activite/catalogue` et `/activite/statistiques`. Ce ne sont pas des
 * replis sans URL : on y arrive par un bouton nommé, le bouton système « précédent »
 * ramène ici, et l'adresse se garde en favori.
 *
 * Les sections vivent dans `routes/activity/`, comme `routes/settings/` l'a fait pour
 * Réglages. Ce fichier n'assemble plus que les états de l'écran et l'état partagé : la
 * séance ouverte et la feuille en cours.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';

import { LinkButton, PageHead, Rule } from '@/components/ui';
import { activityApi, type ActivityItem } from '@/features/activity/api';
import { useAiStatus } from '@/features/ai/useAiStatus';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from './Activity.module.css';
import { ActivitySheet, type SheetTarget } from './activity/ActivitySheet';
import { NewActivitySheet } from './activity/NewActivitySheet';
import { AppleImport } from './activity/AppleImport';
import { CircuitsSection } from './activity/Circuits.section';
import { History } from './activity/History';
import { Journal } from './activity/Journal';
import { toSession, useInvalidateActivity, type Session } from './activity/shared';

export function Activity() {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const ai = useAiStatus();
  const navigate = useNavigate();

  const [picked, setPicked] = useState<Session | null>(null);
  const [sheet, setSheet] = useState<SheetTarget | null>(null);
  /**
   * L'assistant de création, distinct de la feuille de correction.
   *
   * Corriger une activité n'est pas un parcours : on vient changer un champ, pas dérouler
   * deux étapes. Les deux surfaces se ressemblent et font des choses différentes — les
   * confondre obligerait l'une des deux à porter les compromis de l'autre.
   */
  const [creating, setCreating] = useState(false);

  // Choisir une séance depuis l'historique doit **se voir**. L'historique est sous le
  // journal : sans ce défilement, « ouvrir » après avoir descendu la page ne montrait
  // rien du tout.
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (picked === null) return;
    logRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
  }, [picked]);

  const { data, isPending } = useQuery({
    queryKey: keys.activity.overview(),
    queryFn: activityApi.overview,
  });

  const remove = useMutation({
    mutationFn: (item: ActivityItem) =>
      item.kind === 'run'
        ? activityApi.deleteRun(item.id, item.token)
        : activityApi.deleteWorkout(item.id, item.token),
    onSuccess: (_removed, item) => {
      // Le journal ne doit pas rester ouvert sur une séance qui n'existe plus : sans
      // cela il afficherait le refus du serveur au lieu de retomber sur la précédente.
      if (item.kind === 'workout' && picked?.id === item.id) setPicked(null);
      invalidate();
      notify('Activité supprimée.', 'signal');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Suppression impossible.', 'recover');
      invalidate();
    },
  });

  const duplicate = useMutation({
    mutationFn: (item: ActivityItem) =>
      // Le jour vient du serveur, jamais de l'horloge du téléphone.
      activityApi.duplicateWorkout(item.id, data?.today ?? item.date),
    onSuccess: (workout) => {
      invalidate();
      setPicked(toSession(workout));
      notify('Séance dupliquée avec ses exercices.', 'effort');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Duplication impossible.', 'recover');
    },
  });

  const today = data?.today;

  const sessions: Session[] = (data?.history ?? [])
    .filter((row) => row.kind === 'workout')
    .map((row) => ({ id: row.id, date: row.date, label: row.label }));

  // Une séance tout juste créée n'est pas encore dans l'historique relu : le temps d'un
  // aller-retour, le journal montrerait la précédente. On la place en tête jusqu'à ce que
  // l'historique la rattrape.
  if (picked !== null && !sessions.some((item) => item.id === picked.id)) {
    sessions.unshift(picked);
  }

  const currentId = picked?.id ?? sessions[0]?.id ?? null;

  return (
    <div className={cx('wrap', styles.screen)}>
      {/* Les deux portes vers ce qui a quitté cet écran. Des liens et non des boutons :
          ce sont des navigations, elles s'ouvrent dans un onglet et s'annoncent comme
          telles à la synthèse vocale. */}
      <PageHead
        eyebrow="Domaine Activité"
        title={<>Courses &amp; séances</>}
        actions={
          <>
            <LinkButton to="/activite/courses">Courses</LinkButton>
            {/* Pas de lien vers `/activite/seances` ici : la section juste en dessous en
                porte un, au pied de ses cartes, et deux portes vers la même page dans le
                même écran font hésiter au lieu d'aider. */}
            <LinkButton to="/activite/catalogue">Catalogue</LinkButton>
            <LinkButton to="/activite/charges">Charges</LinkButton>
            <LinkButton to="/activite/statistiques">Statistiques</LinkButton>
          </>
        }
      />

      {/* **En tête, et devant le journal.** Une séance Cadence est le geste le plus direct
          de l'écran — un appui et elle démarre — là où consigner une série suppose d'avoir
          déjà commencé. C'est le même arbitrage qui avait fait passer le journal devant les
          statistiques : ce qu'on fait passe devant ce qu'on lit. */}
      <CircuitsSection />

      <Rule>Séance</Rule>
      <div ref={logRef}>
        <Journal
          sessions={sessions}
          currentId={currentId}
          onPick={setPicked}
          ready={today !== undefined}
          onNew={() => {
            setCreating(true);
          }}
          onEditWorkout={(id) => {
            const session = sessions.find((item) => item.id === id);
            if (session === undefined) return;
            setSheet({
              kind: 'workout',
              editing: { kind: 'workout', id, date: session.date },
            });
          }}
        />
      </div>

      <Rule>Historique</Rule>
      <History
        data={data}
        isPending={isPending}
        removing={remove.isPending}
        onOpen={(row) => {
          // Une course n'a pas de journal à ouvrir en place : son détail est une page,
          // avec ses paliers et sa dérive. Une séance, elle, se choisit ici même.
          if (row.kind === 'run') {
            void navigate(`/activite/course/${String(row.id)}`);
            return;
          }
          // Choisir, pas charger. Le journal relit la séance lui-même et affiche en
          // place ce que le serveur refuse.
          setPicked({ id: row.id, date: row.date, label: row.label });
        }}
        onEdit={(row) => {
          const kind = row.kind === 'run' ? 'run' : 'workout';
          setSheet({ kind, editing: { kind, id: row.id, date: row.date } });
        }}
        onDuplicate={(row) => {
          duplicate.mutate(row);
        }}
        onRemove={(row) => {
          remove.mutate(row);
        }}
      />

      {/* Même intention que le formulaire de séance, par une autre porte. Sans clé, la
          carte n'apparaît pas : un import qui ne peut pas lire n'a rien à proposer, et
          les deux formulaires manuels suffisent à tout (`IA-07`). L'état de l'assistance
          se lit dans Réglages. */}
      {ai.enabled && (
        <>
          <Rule>Import</Rule>
          <AppleImport today={today} />
        </>
      )}

      {/* L'assistant est remonté à chaque ouverture : ses étapes repartent du début,
          sans effet de bord d'une ouverture sur la suivante. */}
      {today !== undefined && (
        <NewActivitySheet
          key={creating ? 'open' : 'closed'}
          open={creating}
          today={today}
          onClose={() => {
            setCreating(false);
          }}
          onSaved={(workout) => {
            if (workout !== null) setPicked(toSession(workout));
          }}
        />
      )}

      {/* La feuille de **correction**, remontée à chaque ouverture : ses champs repartent
          de la ligne visée, sans effet de bord d'une ouverture sur la suivante. */}
      {sheet !== null && today !== undefined && (
        <ActivitySheet
          key={`${sheet.kind}-${sheet.editing?.id ?? 'new'}`}
          target={sheet}
          today={today}
          onClose={() => {
            setSheet(null);
          }}
          onSaved={(workout) => {
            setSheet(null);
            if (workout !== null) setPicked(toSession(workout));
          }}
        />
      )}
    </div>
  );
}
