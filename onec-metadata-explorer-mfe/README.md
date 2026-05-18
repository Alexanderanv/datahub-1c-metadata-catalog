# 1C Metadata Explorer MFE

Read-only DataHub Micro Frontend for domain-specific 1C metadata.

The app shows:

- 1C datasets from platform `urn:li:dataPlatform:1c-enterprise`;
- infobase-level grouping from `DatasetProperties.customProperties.infobaseName`;
- common and kind-specific custom aspects: `oneCObjectProperties`,
  `oneCCatalogProperties`, `oneCDocumentProperties`, `oneCRegisterProperties`;
- DB-neutral column mapping from `oneCDbMapping` and `MapsToDbTable`
  (`dbTableName` / `dbColumnName`);
- domain relationships from `oneCDomainRelationships` / GraphQL relationships:
  `HasTabularPart`, `IsTabularPartOf`, `RefersToObject`,
  `IsReferencedByObject`;
- standard `schemaMetadata.fields` as the current field-level source.

The navigation tree covers all dataset-like 1C metadata kinds currently
supported by the connector: constants, catalogs, documents, characteristic
plans, charts of accounts, calculation type plans, information/accumulation/
accounting/calculation registers, enumerations, and tabular sections. HTTP/Web
services are emitted as DataFlow/DataJob integration metadata and remain visible
in standard DataHub navigation; this MFE focuses on dataset-like 1C objects and
their custom aspects.

Governance editing is intentionally out of scope for this MFE. Tags, glossary
terms, ownership, domains and descriptions stay in the standard DataHub UI.

## Local development

```bash
cd onec-metadata-explorer-mfe
npm ci
npm start
```

Open:

- standalone app: `http://localhost:3002/`;
- remote entry: `http://localhost:3002/remoteEntry.js`.

The dev server proxies `/api/graphql` to local GMS on `http://localhost:8080`
and adds `X-DataHub-Actor: urn:li:corpuser:datahub`. When the MFE runs inside
DataHub frontend, it uses the existing DataHub session cookie instead.

## DataHub MFE config

DataHub frontend must be configured with an MFE entry like this:

```yaml
subNavigationMode: false
microFrontends:
  - id: onec-metadata-explorer
    label: 1C Metadata Explorer
    path: /onec-metadata-explorer
    remoteEntry: http://localhost:3002/remoteEntry.js
    module: onecMetadataExplorerMFE/mount
    flags:
      enabled: true
      showInNav: true
    navIcon: Database
```

Expected DataHub URL after registration:

```text
http://localhost:9002/mfe/onec-metadata-explorer
```

Bake or mount this MFE config through the DataHub frontend deployment mechanism
used in your environment.

## Build

```bash
npm run typecheck
npm run build
```

For production/static hosting, set `MFE_PUBLIC_PATH` to the final URL prefix
before building so webpack can load chunks from the correct location.
