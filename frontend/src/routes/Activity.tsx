/**
 * Écran Activité — les séances tabata, la course, et ce qu'on a fait.
 *
 * **Ce qu'on fait passe devant ce qu'on lit.** L'écran était un tableau de bord auquel on
 * avait ajouté un formulaire : trois sections de statistiques, puis le journal, puis la
 * saisie. Le journal est passé en tête, puis les statistiques ont quitté la page — et la
 * phase 5 de `docs/refonte-activite.md` a emporté le journal lui-même avec la musculation
 * saisie série par série.
 *
 * **Ce qui reste tient en trois gestes** : déclarer une séance faite, enregistrer une
 * course, relire les deux. Le catalogue et les statistiques ont disparu avec le fichier
 * qui les nourrissait ; les charges et les circuits ont leur adresse.
 *
 * Les sections vivent dans `routes/activity/`, comme `routes/settings/` l'a fait pour
 * Réglages. Ce fichier n'assemble plus que les états de l'écran et la feuille en cours.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { Button, Card, CardHead, LinkButton, PageHead, Rule } from '@/components/ui';
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
import { useInvalidateActivity } from './activity/shared';

export function Activity() {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const ai = useAiStatus();
  const navigate = useNavigate();

  const [sheet, setSheet] = useState<SheetTarget | null>(null);
  /**
   * L'assistant de saisie, distinct de la feuille de correction.
   *
   * Corriger une course n'est pas un parcours : on vient changer un champ, pas dérouler
   * deux étapes. Les deux surfaces se ressemblent et font des choses différentes — les
   * confondre obligerait l'une des deux à porter les compromis de l'autre.
   */
  const [creating, setCreating] = useState(false);

  const { data, isPending } = useQuery({
    queryKey: keys.activity.overview(),
    queryFn: activityApi.overview,
  });

  /**
   * Supprimer, des deux côtés de l'historique fusionné.
   *
   * Une séance tabata part par `deleteSession`, qui emporte ses séries : c'est ce qui
   * autorise « je l'ai fait » à ne rien demander avant d'écrire. Sans cette porte, un
   * tabata déclaré deux fois — ce que **D6** rend possible — comptait pour toujours.
   */
  const remove = useMutation({
    mutationFn: (item: ActivityItem) =>
      item.kind === 'run'
        ? activityApi.deleteRun(item.id, item.token)
        : activityApi.deleteSession(item.id, item.token),
    onSuccess: () => {
      invalidate();
      notify('Activité supprimée.', 'signal');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Suppression impossible.', 'recover');
      invalidate();
    },
  });

  const today = data?.today;

  return (
    <div className={cx('wrap', styles.screen)}>
      {/* Les portes vers ce qui a quitté cet écran. Des liens et non des boutons : ce sont
          des navigations, elles s'ouvrent dans un onglet et s'annoncent comme telles à la
          synthèse vocale. */}
      <PageHead
        eyebrow="Domaine Activité"
        title={<>Courses &amp; séances</>}
        actions={
          <>
            <LinkButton to="/activite/courses">Courses</LinkButton>
            {/* Pas de lien vers `/activite/seances` ici : la section juste en dessous en
                porte un, au pied de ses cartes, et deux portes vers la même page dans le
                même écran font hésiter au lieu d'aider. */}
            <LinkButton to="/activite/charges">Charges</LinkButton>
          </>
        }
      />

      {/* **En tête.** Une séance Cadence est le geste le plus direct de l'écran — un appui
          et elle démarre. C'est le même arbitrage qui avait fait passer le journal devant
          les statistiques : ce qu'on fait passe devant ce qu'on lit. */}
      <CircuitsSection />

      {/* **Le seul geste manuel qui reste.** Une séance se déclare depuis sa carte, en un
          appui ; une course, elle, porte des chiffres que personne d'autre ne connaît —
          temps, allure, distance — et il faut bien un formulaire pour les recueillir. */}
      <Rule>Course</Rule>
      <Card>
        <CardHead>
          <div>
            <h3>Sortie</h3>
            <p className={styles.note}>
              La capture d’une montre, ou les quatre chiffres à la main.
            </p>
          </div>
          <div className={styles.headActions}>
            <Button
              variant="primary"
              disabled={today === undefined}
              onClick={() => {
                setCreating(true);
              }}
            >
              Enregistrer une course
            </Button>
          </div>
        </CardHead>
      </Card>

      <Rule>Historique</Rule>
      <History
        data={data}
        isPending={isPending}
        removing={remove.isPending}
        onOpen={(row) => {
          // Le détail d'une course est une page, avec ses paliers et sa dérive. Une
          // séance n'en a pas : elle dit ce que Cadence a joué, et l'historique le dit
          // déjà en entier.
          void navigate(`/activite/course/${String(row.id)}`);
        }}
        onEdit={(row) => {
          setSheet({ kind: 'run', editing: { kind: 'run', id: row.id, date: row.date } });
        }}
        onRemove={(row) => {
          remove.mutate(row);
        }}
      />

      {/* Même intention que le formulaire de course, par une autre porte. Sans clé, la
          carte n'apparaît pas : un import qui ne peut pas lire n'a rien à proposer, et
          le formulaire manuel suffit à tout (`IA-07`). L'état de l'assistance se lit
          dans Réglages. */}
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
        />
      )}

      {/* La feuille de **correction**, remontée à chaque ouverture : ses champs repartent
          de la ligne visée, sans effet de bord d'une ouverture sur la suivante. */}
      {sheet !== null && today !== undefined && (
        <ActivitySheet
          key={`run-${sheet.editing?.id ?? 'new'}`}
          target={sheet}
          today={today}
          onClose={() => {
            setSheet(null);
          }}
        />
      )}
    </div>
  );
}
