# Dossier pdf_uploads — Articles payants

Ce dossier est destiné aux **PDFs d'articles scientifiques** dont l'accès
au texte intégral n'est pas disponible gratuitement.

## Comment ça fonctionne

Chaque semaine, l'email de validation liste les articles sélectionnés
pour lesquels le pipeline n'a pas pu récupérer le texte intégral
(article payant non disponible sur PubMed Central, Europe PMC ou Unpaywall).

Pour chacun d'eux, si tu peux obtenir le PDF :

1. **Nomme le fichier avec le PMID de l'article** : `{PMID}.pdf`
   (le PMID est indiqué dans l'email de validation)

2. **Dépose le PDF dans ce dossier** (`pdf_uploads/`)

3. **Relance la génération** depuis GitHub Actions
   (ou attends la génération automatique du lundi suivant)

## Exemple

Si l'article a le PMID `38547291`, dépose le fichier comme suit :
```
pdf_uploads/38547291.pdf
```

## Comment obtenir les articles payants légalement

- **Accès institutionnel** : via l'intranet AP-HP ou l'université
- **ResearchGate** : beaucoup d'auteurs partagent leurs articles
- **Email aux auteurs** : un email courtois suffit souvent
  (mention que c'est pour Endo Debrief, une chaîne de vulgarisation scientifique)
- **Open Access Button** : https://openaccessbutton.org/
- **Unpaywall extension** : https://unpaywall.org/products/extension

## Important

Ce dossier est dans `.gitignore` — les PDFs ne seront PAS commités sur GitHub
(droits d'auteur). Ils sont utilisés localement ou dans GitHub Actions
via des secrets chiffrés.

⚠️ **Ne jamais utiliser Sci-Hub ou tout autre service contournant les paywalls.**
Ce pipeline est conçu pour utiliser uniquement les voies d'accès légales.
