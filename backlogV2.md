# Backlog fonctionnel — Metric (v2, sans UI)

Récapitulatif exhaustif des **capacités** de l'application, rédigé pour la refaire de
zéro. Volontairement **agnostique de l'interface** : tout ce qui relève de la
présentation (design, cartes, modales, thème, navigation, graphiques, accessibilité,
responsive) est sorti de ce document et traité dans le fichier de guidelines UI.

Ce qui reste ici : le **domaine métier**, les **règles de calcul**, les **données
exposées par l'API** et les **contraintes de saisie**. Chaque ligne décrit un
comportement observable, pas un écran.

- **Périmètre** : suivi sportif perso (corps, activité, nutrition, hydratation,
  suppléments, planning, objectifs IA), mono-utilisateur, français, unités métriques.
- **Stack de référence** : FastAPI (Python) + stockage Nextcloud/WebDAV en CSV ·
  React + Vite + TypeScript + TanStack Query · IA via OpenRouter (modèles gratuits).
- **Statut** : sections 1 à 11 **réalisées** (hors mentions contraires),
  section 12 **nouveau**, section 13 **reste à faire**.

---

## 1. Authentification & sécurité — `AUTH`

| ID | Fonctionnalité | Description |
|---|---|---|
| AUTH-01 | Connexion mono-utilisateur | Identifiant + mot de passe comparés aux valeurs de configuration serveur. Un seul compte : ni inscription, ni multi-comptes. |
| AUTH-02 | Mot de passe haché en Argon2id | Jamais de mot de passe en clair : seul un hash Argon2id (sel embarqué) est conservé. Vérification par re-dérivation et comparaison en temps constant. |
| AUTH-03 | Session par jeton JWT | La connexion émet un JWT signé (7 jours par défaut) renvoyé en `Authorization: Bearer`. La session survit à la fermeture de l'app et au redémarrage de l'appareil. |
| AUTH-04 | Anti-brute-force | Au-delà de 5 échecs en 60 s depuis une même IP : `429` avec délai d'attente annoncé. Le mot de passe est vérifié même si l'identifiant est faux, pour ne pas révéler par le timing quel champ est incorrect. |
| AUTH-05 | Protection de toutes les routes de données | Chaque endpoint métier exige un jeton valide, sinon `401`. Seuls la santé, la doc et le flux iCal (protégé par clé) sont publics. |
| AUTH-06 | Expiration de session gérée côté client | Un `401` purge le jeton local et invalide la session courante, avec un motif exploitable par l'interface. |
| AUTH-07 | Déconnexion manuelle | Action explicite qui efface le jeton et termine la session. |
| AUTH-08 | Outil de génération du hash | Script CLI produisant le hash Argon2id à coller en configuration, sans manipuler de mot de passe en clair dans un fichier. |

## 2. Stockage & données — `STO`

| ID | Fonctionnalité | Description |
|---|---|---|
| STO-01 | Stockage exclusif sur Nextcloud via WebDAV | Toutes les données vivent dans un dossier Nextcloud, sans base de données. Le backend est seul détenteur des identifiants. |
| STO-02 | Données en CSV lisibles sans l'app | Un fichier CSV à en-tête explicite par domaine. Les données restent exploitables dans un tableur même si l'app disparaît. |
| STO-03 | Écriture en ajout (append) | Nouvelles entrées ajoutées en fin de fichier plutôt que réécriture complète : plus sûr en cas d'interruption, cohérent avec le versioning Nextcloud. |
| STO-04 | Migration automatique des en-têtes CSV | Nouvelle colonne = remappage des anciennes lignes par nom de colonne, valeurs manquantes laissées vides. Aucune migration manuelle. |
| STO-05 | Garde anti-conflit multi-appareils | Toute modification ou suppression envoie les valeurs attendues de la ligne visée ; le serveur refuse en `409` si elles ont changé. Évite d'écraser la mauvaise ligne quand l'app est ouverte sur deux appareils. |
| STO-06 | Cache mémoire des lectures | Contenus CSV mis en cache quelques dizaines de secondes, invalidés à chaque écriture. Les vues agrégées tirent une dizaine de fichiers sans saturer Nextcloud. |
| STO-07 | Stockage de fichiers binaires | Photos de repas téléversées dans une arborescence datée à côté des CSV, création automatique des dossiers parents. |
| STO-08 | Résilience réseau & rate-limit | Réessai des opérations WebDAV sur erreur transitoire et sur `429`, en honorant `Retry-After`. Connexions limitées et maintenues en keep-alive. |
| STO-09 | Erreurs de stockage traduites | Panne ou saturation Nextcloud → `502`/`503` avec message français exploitable, jamais une 500 brute. |
| STO-10 | Versioning des données | L'historique natif Nextcloud sert de versioning, complété par les écritures en ajout. Retour à une version antérieure possible sans outil tiers. |
| STO-11 | Outil de vérification du stockage | Script qui écrit puis relit une ligne de test, pour diagnostiquer la configuration WebDAV avant même de lancer l'API. |

## 3. Socle API — `API`

| ID | Fonctionnalité | Description |
|---|---|---|
| API-01 | API HTTP structurée par domaine | REST découpée en routeurs (auth, poids, mensurations, activité, exercices, nutrition, hydratation, suppléments, objectifs, import, réglages, planning, agrégats). Chaque domaine testable isolément. |
| API-02 | Configuration centralisée par `.env` | URL Nextcloud, identifiants, secret JWT, origines CORS, paramètres IA dans un unique fichier d'environnement. Aucun secret dans le code ni côté client. |
| API-03 | CORS configurable | Origines autorisées paramétrables (dev local + domaine de production). |
| API-04 | Endpoint de santé | Route publique renvoyant l'état du service, pour vérification manuelle et supervision. |
| API-05 | Documentation interactive | OpenAPI et interface d'essai générées automatiquement ; chaque endpoint testable depuis le navigateur. |
| API-06 | Validation stricte des entrées | Validation par schéma avec bornes de vraisemblance (poids 0–500 kg, réps 1–200, FC 1–260, volume 0–5000 ml…). Saisie aberrante rejetée avant le stockage. |
| API-07 | Codes d'erreur stables et typés | Chaque échec métier porte un code machine (`storage_unavailable`, `conflict`, `ai_quota`, `session_expired`…) en plus du message. Le client mappe les codes vers ses propres formulations, sans parser du texte. |

## 4. Corps : poids & mensurations — `BODY`

| ID | Fonctionnalité | Description |
|---|---|---|
| BODY-01 | Enregistrer une pesée | Poids, date (jamais future) et note optionnelle, écrits immédiatement dans le CSV. |
| BODY-02 | Modifier ou supprimer une pesée | Édition et suppression d'une entrée existante, sous garde anti-conflit. |
| BODY-03 | Indicateurs de poids | Dernier poids, variation sur les 8 dernières pesées, série des valeurs et écart restant jusqu'à l'objectif, exposés comme données prêtes à afficher. |
| BODY-04 | Série temporelle du poids | Série complète des pesées, ordonnée, avec min / max / amplitude. |
| BODY-05 | Tendance lissée 7 jours | Moyenne mobile sur fenêtre glissante de 7 jours, calculée côté serveur, pour dégager la direction réelle malgré les fluctuations quotidiennes. |
| BODY-06 | Historique des pesées | Historique paginé de la plus récente à la plus ancienne, chaque entrée identifiable pour édition. |
| BODY-07 | Enregistrer des mensurations | Taille, bras, poitrine, hanches, cuisse — toutes optionnelles, au moins une requise, datées. |
| BODY-08 | Indicateurs de mensurations | Pour chaque mesure : dernière valeur, delta par rapport à la précédente et sens de variation. |
| BODY-09 | Historique et édition des mensurations | Historique complet des lignes, modifiables et supprimables comme les pesées. *(était BODY-11, reste à faire)* |
| BODY-10 | Composition corporelle | Pourcentage de masse grasse suivi comme mesure supplémentaire du domaine Corps. *(reste à faire)* |

## 5. Activité sportive — `ACT`

| ID | Fonctionnalité | Description |
|---|---|---|
| ACT-01 | Enregistrer une course | Date, distance en km, temps `mm:ss` ou `h:mm:ss`, FC moyenne et dénivelé optionnels. Formats souples acceptés et normalisés (virgule décimale, minutes seules). |
| ACT-02 | Calcul de l'allure | Allure min/km dérivée de la distance et du temps, calculée à la volée pour aperçu et stockée avec la course. |
| ACT-03 | Enregistrer une séance | Type (suggestions : musculation, vélo, natation, HIIT, yoga, marche, football), durée, calories optionnelles. Identifiant stable permettant d'y rattacher des exercices. |
| ACT-04 | Modifier ou supprimer une activité | Courses et séances éditables ; supprimer une séance purge les exercices rattachés. |
| ACT-05 | Détail d'une course | Distance, temps, allure, vitesse, FC moyenne, dénivelé, note, exposés comme ressource unitaire. |
| ACT-06 | Catalogue d'exercices | Ajout et retrait d'exercices rattachés à un groupe musculaire (pectoraux, dos, épaules, biceps, triceps, jambes, fessiers, abdos, autre). Retirer un exercice conserve tout l'historique. |
| ACT-07 | Journal d'exercices par séance | Charge × séries × répétitions par exercice (charge 0 = poids du corps), modifiable lors d'une édition ultérieure. |
| ACT-08 | Rappel de la dernière performance | À la sélection d'un exercice, la perf précédente et sa date sont fournies pour choisir sa charge sans consulter l'historique. |
| ACT-09 | Progression des charges par exercice | Par exercice : dernière perf, delta de charge vs fois précédente, et série temporelle de la charge maximale. Groupement par muscle. |
| ACT-10 | Volume hebdomadaire par jour | Minutes d'activité de lundi à dimanche, jours de repos distingués. |
| ACT-11 | Totaux de la semaine | Temps total, nombre de séances, distance cumulée, allure moyenne. Remise à zéro chaque lundi. |
| ACT-12 | Historique du volume hebdomadaire | Série des 8 dernières semaines en minutes, pour vérifier progression ou stabilisation. |
| ACT-13 | Historique d'activité | Liste fusionnée courses + séances, triée du plus récent au plus ancien, avec type, date et durée. |
| ACT-14 | Tonnage et volume par groupe musculaire | Somme charge × séries × réps par exercice, agrégée par muscle et par semaine. Mesure la charge réelle, là où les minutes ne distinguent pas 3 séries de 8 d'une heure de repos. *(nouveau)* |
| ACT-15 | Records personnels et 1RM estimé | Détection automatique d'un record (charge max, ou 1RM estimé par Epley) à l'enregistrement d'un exercice, historisé par exercice. *(nouveau)* |
| ACT-16 | Groupes musculaires négligés | Nombre de jours depuis la dernière sollicitation de chaque groupe, pour signaler les déséquilibres et alimenter la génération IA de planning. *(nouveau)* |
| ACT-17 | Duplication de la dernière séance | Créer une séance pré-remplie à partir d'une séance passée, exercices compris, pour saisir une répétition de routine en une action. *(nouveau)* |
| ACT-18 | Ressenti de séance (RPE) | Note d'effort perçu 1–10 optionnelle par séance, stockée avec l'activité et transmise à l'IA comme signal de charge et de fatigue. *(nouveau)* |

## 6. Nutrition — `NUT`

| ID | Fonctionnalité | Description |
|---|---|---|
| NUT-01 | Ajouter un repas photo + commentaire | Photo (capture ou fichier) et/ou description libre ; au moins l'un des deux requis. |
| NUT-02 | Rangement automatique des photos | Stockage sur Nextcloud en `nutrition/photos/AAAA/MM/JJ/`, nom unique horodaté, consultable hors de l'app. |
| NUT-03 | Typage du repas | Petit-déj / déjeuner / dîner / collation, présélectionné selon l'heure courante. |
| NUT-04 | Analyse IA de l'assiette | Photo et/ou description envoyées à un modèle vision qui estime protéines, sucres ajoutés et calories du repas entier. Les valeurs sont proposées, jamais imposées. |
| NUT-05 | Saisie et ajustement manuel des macros | Protéines, sucres ajoutés, calories saisissables ou corrigeables à la main, avec ou sans IA. |
| NUT-06 | Totaux nutritionnels du jour | Protéines du jour vs objectif, sucres ajoutés vs plafond, calories cumulées quand renseignées. |
| NUT-07 | Liste des repas | Chaque repas avec référence photo, heure, type, commentaire et macros ; liste bornée ou complète selon la requête. |
| NUT-08 | Service sécurisé des photos | Endpoint authentifié restreint au dossier photos, tout parcours d'arborescence bloqué. Chemins uniques → réponses cachables durablement. |
| NUT-09 | Modifier ou supprimer un repas | Correction de l'heure, du type, du commentaire ou des macros ; photo d'origine et source préservées. |
| NUT-10 | Repas favoris / récurrents | Enregistrer un repas comme modèle réutilisable (nom + macros) et le rejouer en une action, sans photo ni IA. Couvre les repas identiques du quotidien. *(nouveau)* |
| NUT-11 | Base produits & code-barres | Recherche dans une base publique type Open Food Facts et scan de code-barres pour remplir les macros. Complète l'estimation IA sur les produits industriels. *(reste à faire)* |

## 7. Hydratation — `HYD` *(nouveau domaine)*

| ID | Fonctionnalité | Description |
|---|---|---|
| HYD-01 | Enregistrer une prise de boisson | Volume en ml et horodatage, avec type optionnel (eau, café, thé, boisson sportive, autre). Prérequis de la heatmap boissons. |
| HYD-02 | Raccourcis de volume | Volumes prédéfinis paramétrables (verre 250 ml, bouteille 500 ml, gourde 750 ml) pour enregistrer une prise en une action. |
| HYD-03 | Total du jour et objectif | Volume cumulé du jour rapporté à un objectif quotidien réglable, avec ratio d'atteinte. |
| HYD-04 | Correction d'une prise | Modification ou suppression d'une prise du jour, pour rattraper une erreur de saisie. |
| HYD-05 | Historique et moyenne | Série des volumes quotidiens, moyenne sur 7 et 30 jours, nombre de jours ayant atteint l'objectif. |

## 8. Suppléments — `SUP`

| ID | Fonctionnalité | Description |
|---|---|---|
| SUP-01 | Configurer son planning de suppléments | Nom, dose, unité (g, mg, UI, gélule, ml) et moment de prise. Le planning trié par horaire sert de base à la checklist quotidienne. |
| SUP-02 | Retirer un supplément | Retrait du planning sans perdre l'historique des prises déjà enregistrées. |
| SUP-03 | Checklist du jour | Les suppléments actifs sont cochables ; cocher enregistre une prise horodatée. L'état repart vierge chaque jour. |
| SUP-04 | Écriture optimiste | La bascule est appliquée localement avant réponse serveur et annulée en cas d'échec. |
| SUP-05 | Décocher une prise | Supprime la prise du jour correspondante dans le journal. |
| SUP-06 | Ratio du jour | Nombre de suppléments pris sur nombre d'actifs, et indicateur booléen « journée complète ». Base de la heatmap `HEAT-03`. |

## 9. Planning sport — `PLAN`

| ID | Fonctionnalité | Description |
|---|---|---|
| PLAN-01 | Calendrier mensuel | Par jour : séances prévues et séances réellement effectuées, sur un mois navigable, semaine commençant le lundi. |
| PLAN-02 | Planifier, modifier, supprimer une séance | Date, heure optionnelle, type (course / muscu / autre), titre avec suggestions, durée, note de contenu. |
| PLAN-03 | Génération IA du planning | À partir de la fréquence réelle des 4 dernières semaines, des groupes musculaires travaillés (dont `ACT-16`), de l'objectif actif et de contraintes libres, l'IA propose 1 ou 2 semaines. Elle alterne les groupes, prévoit la récupération et évite de dupliquer l'existant. |
| PLAN-04 | Aperçu puis adoption | Les séances proposées sont retournées avant écriture et retirables individuellement ; l'adoption enregistre le reste en une fois, marqué source IA. |
| PLAN-05 | Export iCal abonnable | Flux `.ics` protégé par clé secrète stable, abonnable depuis Apple Calendar / Google Agenda, également téléchargeable ponctuellement. |
| PLAN-06 | Écart plan / réalisé | Pour chaque semaine : séances planifiées vs effectuées, et taux de respect du planning. Alimente le bilan hebdomadaire. *(nouveau)* |

## 10. Objectifs IA — `GOAL`

| ID | Fonctionnalité | Description |
|---|---|---|
| GOAL-01 | Génération d'un objectif personnalisé | Objectif unique, chiffré, daté sur 4 à 8 semaines, avec justification adossée aux données réelles. Données maigres → repli sur un objectif de régularité. |
| GOAL-02 | Résumé de données envoyé au modèle | Condensé factuel uniquement : poids actuel et amplitude, séances et courses, distance cumulée, protéines moyennes, hydratation moyenne, suppléments suivis. Jamais les fichiers entiers. |
| GOAL-03 | Adopter, régénérer, abandonner | Une suggestion peut être adoptée, régénérée ou abandonnée. Les objectifs adoptés sont conservés avec date de création et statut. |
| GOAL-04 | Calcul de progression | La métrique de l'objectif est interprétée pour produire une progression réelle : poids, séances/semaine, km/semaine, protéines/jour ou hydratation/jour, avec libellé chiffré et ratio. |
| GOAL-05 | États de l'objectif | Trois états exposés : aucune proposition, suggestion en attente, objectif actif avec échéance et progression. |
| GOAL-06 | Historique des objectifs | Objectifs passés conservés avec leur résultat final (atteint / partiel / abandonné), pour donner du contexte à la génération suivante. *(nouveau)* |

## 11. Couche IA & imports — `IA` / `IMP`

| ID | Fonctionnalité | Description |
|---|---|---|
| IA-01 | Client OpenRouter | Client unique (API compatible OpenAI) pour toutes les fonctions IA : objectifs, planning, analyse de repas, import Apple, bilan hebdo. Modèle préféré configurable. |
| IA-02 | Découverte des modèles gratuits | Liste des modèles à coût nul récupérée dynamiquement, filtrée (modération, embedding, TTS exclus), classée par pertinence et taille, cachée une heure. |
| IA-03 | Bascule automatique multi-modèles | Sur `429` ou réponse inexploitable, réessai sur le modèle configuré puis cascade sur les autres modèles gratuits. Échec total → message distinguant quota saturé et autre erreur. |
| IA-04 | Support vision | Seuls les modèles acceptant une entrée image entrent dans la cascade pour les appels sur image. |
| IA-05 | Extraction JSON robuste | Nettoyage du raisonnement (`<think>…`) et extraction du premier objet JSON valide par équilibrage des accolades. |
| IA-06 | Préparation des images | Redimensionnement à 1024 px max, conversion JPEG, encodage data URL, pour réduire coût et latence. |
| IA-07 | Dégradation propre sans clé | Sans clé API, l'app fonctionne intégralement en saisie manuelle et les fonctions IA renvoient un message clair. L'IA est un confort, jamais un prérequis. |
| IA-08 | Bilan hebdomadaire | Une fois par semaine, l'IA produit un court bilan factuel : ce qui a progressé, ce qui a décroché, une action concrète pour la semaine suivante. Généré à la demande, historisé. *(nouveau)* |
| IA-09 | Conversation contextuelle | Poser une question en français sur ses propres données et recevoir une réponse qui s'y appuie. Le modèle reçoit un **condensé factuel** — jamais les fichiers entiers — et le condensé est affiché à l'écran. *(nouveau)* |
| IA-10 | Mémoire de santé | Ce que l'utilisateur dit d'important sur sa santé — blessure, sommeil, traitement, contrainte — est **proposé** à la conservation, validé par lui, et réinjecté dans les échanges suivants. Rien n'est retenu sans validation. *(nouveau)* |
| IA-11 | Gestion de la mémoire | Lire, corriger et retirer ce qui a été retenu, à la main. Disponible **sans clé API** : la mémoire est un carnet, pas une fonction IA. *(nouveau)* |
| IA-12 | Garde-fou médical | L'assistant n'est pas un médecin : ni diagnostic, ni traitement, ni interprétation de symptôme. Devant une plainte physique il le dit et renvoie vers un professionnel. La consigne le porte, l'écran l'affiche. *(nouveau)* |
| IMP-01 | Analyse d'un screenshot d'entraînement | Capture Apple Fitness / Apple Watch envoyée à un modèle vision qui en extrait les valeurs. L'endpoint analyse seulement : rien n'est écrit sans validation. |
| IMP-02 | Pré-remplissage | Type, date, distance, temps, FC moyenne, dénivelé, calories, type de séance pré-remplis et tous modifiables avant import. |
| IMP-03 | Conversion et normalisation | Miles → km, `28:45` → minutes décimales, dates relatives → date absolue non future. Les valeurs absentes restent vides plutôt qu'inventées. |
| IMP-04 | Détection de doublon probable | Avertissement si une activité du même type existe à la même date avec une durée proche à une minute près. |
| IMP-05 | Traçabilité de la source | `source=apple` vs `manual` dans le CSV : l'origine d'une donnée est lisible jusque dans le fichier. |
| IMP-06 | Gestion des captures illisibles | Capture non exploitable → message explicite, avec relance de l'analyse ou saisie manuelle possible. |
| IMP-07 | Import Apple étendu | Captures « anneaux d'activité », poids Apple Health, et analyse de plusieurs captures en une fois. *(reste à faire)* |

## 12. Agrégats, heatmaps & assiduité — `AGG` / `HEAT`

Section qui remplace l'ancienne « Visualisation & gamification » : ne subsistent que
les **données calculées**, la façon de les dessiner relevant des guidelines UI.

| ID | Fonctionnalité | Description |
|---|---|---|
| AGG-01 | Endpoint d'agrégats du tableau de bord | Une requête unique retourne tous les indicateurs de synthèse (activité, poids, nutrition, hydratation, suppléments, objectif, série), au lieu d'une dizaine d'appels parallèles. |
| AGG-02 | Totaux d'entraînement | Total de séances toutes catégories, total de la semaine courante, série des 8 dernières semaines, répartition courses / musculation. |
| AGG-03 | Série d'assiduité (streak) | Jours consécutifs avec au moins une donnée saisie, toutes sources confondues (poids, mensurations, courses, séances, repas, hydratation, prises). État des 7 derniers jours, la série d'hier restant valide tant que la journée en cours n'est pas terminée. |
| AGG-04 | Séries temporelles génériques | Pour n'importe quelle métrique suivie : série sur une plage (1 mois / 3 mois / tout) plus statistiques dernier, variation, moyenne, min, max. Un seul contrat réutilisé pour poids, mensurations, volume hebdo, charge par exercice, hydratation. |
| HEAT-01 | Heatmap générique par jour | Un endpoint unique retourne, pour une métrique et une plage de dates, un tableau `date → valeur brute + niveau d'intensité 0–4`. Les jours sans donnée sont explicitement à zéro, pas absents : une année pleine est toujours retournée complète. |
| HEAT-02 | Heatmap entraînement | Intensité dérivée des minutes d'activité du jour (repos, ≤30, ≤60, ≤90, >90 min), courses et séances confondues. Variante filtrable sur la musculation seule. |
| HEAT-03 | Heatmap hydratation | Intensité dérivée du volume bu rapporté à l'objectif quotidien (0, <50 %, <80 %, <100 %, ≥100 %). Dépend de `HYD-01`. |
| HEAT-04 | Heatmap suppléments complets | Un jour est « complet » quand toutes les prises planifiées et actives ce jour-là ont été cochées. Intensité binaire ou en quartiles du ratio pris/prévus, au choix de la requête. Les suppléments ajoutés après coup ne rendent pas rétroactivement les jours passés incomplets. |
| HEAT-05 | Heatmap de saisie | Intensité dérivée du nombre de domaines renseignés dans la journée (poids, repas, activité, hydratation, suppléments) : mesure l'assiduité de suivi elle-même, indépendamment de la performance. |
| HEAT-06 | Détail d'un jour de heatmap | Pour une date donnée, retour du détail correspondant (activités, volume bu, suppléments pris/manqués) afin qu'un jour de la grille soit explorable. |
| HEAT-07 | Statistiques de heatmap | Pour chaque métrique et plage : total de jours actifs, plus longue série, série en cours, meilleur jour. Ce sont les chiffres qui accompagnent la grille. |
| HEAT-08 | Métrique de heatmap configurable | La métrique affichée en évidence est un réglage utilisateur, pas une constante du code. *(reprend VIZ-07)* |

## 13. Reste à faire — `NOT` / `OPS` / `DATA`

| ID | Fonctionnalité | Description |
|---|---|---|
| NOT-01 | Abonnement aux notifications push | Clés VAPID côté serveur et flux d'abonnement Web Push depuis le client. Prérequis technique de tous les rappels. |
| NOT-02 | Planificateur de rappels | Ordonnanceur backend déclenchant les notifications aux créneaux configurés (repas, séance, suppléments, hydratation), fonctionnel même app fermée. |
| NOT-03 | Configuration des rappels | Activation et horaires par type de rappel, stockés comme les autres réglages. |
| OPS-01 | Déploiement HTTPS reproductible | Conteneurisation backend + frontend derrière un reverse-proxy à certificat automatique. HTTPS est indispensable à la PWA et aux notifications. |
| OPS-02 | Documentation d'exploitation | Installation, mise à jour et sauvegarde documentées dans le dépôt, pour redéployer de zéro sans mémoire du contexte. |
| DATA-01 | Export complet des données | Archive de tous les CSV (et optionnellement des photos) téléchargeable en une action, indépendante de Nextcloud. Sauvegarde de sortie et garantie de non-enfermement. *(nouveau)* |
| DATA-02 | File d'attente hors-ligne | Les écritures faites sans réseau sont mises en file côté client et rejouées à la reconnexion, avec résolution des conflits `409`. Une séance saisie en salle sans réseau n'est jamais perdue. *(nouveau)* |
| DATA-03 | Recherche et filtres d'historique | Filtrage des historiques par plage de dates, type et texte libre, côté serveur. Devient nécessaire dès quelques centaines de lignes. *(nouveau)* |
| DATA-04 | Corrélations simples | Mise en regard de deux séries sur une même plage (poids vs calories, allure vs volume hebdo, hydratation vs séances) avec coefficient de corrélation. À traiter comme une lecture, sans prétention causale. *(nouveau, optionnel)* |

---

## Annexe — Jeux de données CSV

| Fichier | Colonnes |
|---|---|
| `body/weight.csv` | date, weight_kg, note, source |
| `body/measurements.csv` | date, waist_cm, arm_cm, chest_cm, hips_cm, thigh_cm, body_fat_pct, note |
| `activity/runs.csv` | date, distance_km, duration_min, pace_min_km, avg_hr, elevation_m, note, source |
| `activity/workouts.csv` | date, type, duration_min, calories, rpe, note, source, id |
| `activity/exercises.csv` | id, name, muscle_group |
| `activity/exercise_log.csv` | workout_id, date, exercise_id, exercise_name, muscle_group, weight_kg, sets, reps, note |
| `nutrition/meals.csv` | datetime, meal_type, comment, photo, protein_g, added_sugar_g, calories, source |
| `nutrition/favorites.csv` | id, name, protein_g, added_sugar_g, calories |
| `nutrition/photos/AAAA/MM/JJ/` | photos de repas (fichiers) |
| `hydration/intake_log.csv` | datetime, volume_ml, kind |
| `supplements/schedule.csv` | id, name, dose, unit, time, frequency, active, created |
| `supplements/intake_log.csv` | datetime, schedule_id, name, dose, unit |
| `planning/plan.csv` | id, date, time, kind, title, duration_min, note, source |
| `goals/goals.csv` | id, created, title, metric, target, unit, deadline, rationale, source, status, outcome |
| `insights/weekly.csv` | week, created, summary, source |
| `insights/memory.csv` | id, created, topic, note, source |
| `settings.csv` | key, value |

### Réglages (`settings.csv`)

| Clé | Défaut | Usage |
|---|---|---|
| `target_weight_kg` | 70 | Écart restant, progression d'objectif |
| `target_protein_g` | 150 | Ratio protéines du jour |
| `max_added_sugar_g` | 30 | Plafond sucres ajoutés |
| `target_hydration_ml` | 2000 | Ratio hydratation, `HEAT-03` |
| `hydration_presets_ml` | 250,500,750 | Raccourcis `HYD-02` |
| `heatmap_metric` | activity | Métrique mise en avant (`HEAT-08`) |
| `reminders_*` | — | Créneaux de rappel (`NOT-03`) |

Backend et frontend partagent les mêmes valeurs de repli : l'app est utilisable
immédiatement, avant tout réglage.