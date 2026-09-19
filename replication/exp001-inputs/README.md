# Réplication EXP-001 — dossier d’entrée sans code ni résultat

But : écrire de zéro un programme qui évalue les3 072 règles de
FAM-001-definition.json et les4 999 ordres grecs fournis. Ne lire ni importer
le code, les tests, les rapports de scores ou les vérificateurs du projet source.
Les corpus ont été reconstitués depuis les sources gelées et leurs empreintes
comparées à celles engagées lors d’EXP-001 ; aucun score attendu n’est fourni.

torah.txt et nt.txt sont UTF-8 sans séparateur ni saut final. L’hébreu conserve
les formes finales dans ce fichier ; les rabattre selon ךםןףץ→כמנפצ avant de
passer aux rangs0..21. L’alphabet grec et les rangs0..23 figurent dans la
définition. L’iota souscrit a été développé en iota dans ce corpus historique.
Ne pas employer la normalisation grecque plus récente des autres expériences.

La définition donne l’ordre exact des paramètres, les positions et le score
centré entier. Important : le voisin v+1 suit toujours l’ordre hébreu original,
même lorsque le parcours de positions est inverse. L’échelle utilise N, longueur
grecque tronquée à un multiple de16, pour les prédictions analysées. Ne pas
employer la longueur non tronquée ni joindre de nouvelles unités.

reference-orders.json contient des listes de16 entiers, utilisées comme la
fonction i→permutation[i]. Recalculer le maximum des3 072 scores dans chacun
des4 999 ordres. Rapporter les scores et nombres de correspondances pour toutes
les règles, tous les ex aequo, le maximum centré, le meilleur compte brut,
les4 999 maxima, le nombre de dépassements inclusifs et p=(1+dépassements)/5000.
Appliquer aussi le filtre exact déclaré, sans introduire une nouvelle règle.

Pour reproduire indépendamment les ordres : Python random.Random(2026091803).
Chaque permutation réinitialise list(range(16)) puis rng.shuffle. Consommer
40 000 permutations, puis199. Pour les taux0.25,0.5,1.0, dans cet ordre, faire
20 essais : pour chacune des1 024 positions, tirer rng.random et, seulement
si ce tirage est inférieur au taux, rng.randrange(24) ; puis199 permutations.
Consommer ensuite deux séries de1 999 permutations. Les4 999 suivantes sont
les ordres du fichier. Aucun score n’intervient dans cette reconstruction.
Cet horaire de générateur est une commodité de reproduction exacte, pas une
nouvelle sélection aléatoire indépendante de l’étude initiale.

Livrables : code neuf, instructions, manifeste des entrées effectivement lues,
version d’environnement, contrôle du générateur, vecteur complet des3 072
résultats observés, maxima des4 999 références et journal d’exécution. Geler
les sorties et leurs empreintes avant de demander les résultats d’origine.
Signaler toute ambiguïté au lieu de consulter l’ancienne implémentation.

Cette tâche est une réplication informatique sur les mêmes transcriptions,
pas une confirmation sur données réservées ni un audit paléographique.
Licences : texte WLC/OSHB, domaine public pour WLC et CC BY4.0 pour le travail
Open Scriptures ; SBLGNT, Michael W. Holmes/SBL/Logos2010, version CC BY4.0.
Les sources et versions exactes sont consignées dans provenance.json.
