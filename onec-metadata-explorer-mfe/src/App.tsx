import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Database,
  ExternalLink,
  FileText,
  Folder,
  FolderTree,
  Network,
  RefreshCw,
  Search,
  Table2,
} from 'lucide-react';
import {
  DEFAULT_SEARCH_PAGE_SIZE,
  fetchOneCDatasetDetail,
  parseOneCAspects,
  searchOneCDatasets,
} from './graphql';
import {
  AttributeColumnMapping,
  DatasetDetail,
  DatasetRef,
  ObjectFilterState,
  OneCAspects,
  OneCDatasetSummary,
  OneCDomainRelationships,
  OneCRelationshipType,
  Relationship,
  SchemaField,
} from './types';
import './App.css';

const RELATIONSHIP_LABELS: Record<string, string> = {
  HasTabularPart: 'Tabular sections',
  IsTabularPartOf: 'Parent object',
  MapsToDbTable: 'Physical DB table',
  RefersToObject: 'References',
  IsReferencedByObject: 'Referenced by',
};

const RELATIONSHIP_ASPECT_FIELDS: Record<OneCRelationshipType, keyof OneCDomainRelationships> = {
  HasTabularPart: 'hasTabularPart',
  IsTabularPartOf: 'isTabularPartOf',
  MapsToDbTable: 'mapsToDbTable',
  RefersToObject: 'refersToObject',
  IsReferencedByObject: 'isReferencedByObject',
};

function getInitialUrn(): string | undefined {
  const params = new URLSearchParams(window.location.search);
  return params.get('urn') ?? undefined;
}

function updateUrnParam(urn: string): void {
  const params = new URLSearchParams(window.location.search);
  params.set('urn', urn);
  window.history.replaceState(null, '', `${window.location.pathname}?${params.toString()}`);
}

function displayName(entity?: DatasetRef | null): string {
  if (!entity) {
    return 'Unknown entity';
  }
  return entity.properties?.qualifiedName || entity.properties?.name || entity.name || entity.urn;
}

function secondaryName(entity?: DatasetRef | null): string {
  if (!entity) {
    return '';
  }
  const primary = displayName(entity);
  const fallback = entity.properties?.name || entity.name || entity.urn;
  return fallback !== primary ? fallback : entity.urn;
}

function customProperty(entity: DatasetRef | undefined | null, key: string): string | undefined {
  return entity?.properties?.customProperties?.find((item) => item.key === key)?.value;
}

function metadataKind(entity: DatasetRef | undefined | null): string | undefined {
  return customProperty(entity, 'metadataKind');
}

function infobaseName(entity: DatasetRef | undefined | null): string {
  return customProperty(entity, 'infobaseName') || 'Unnamed infobase';
}

function objectKind(entity?: OneCDatasetSummary | DatasetDetail | null, aspects?: OneCAspects): string {
  if (!entity) {
    return 'Unknown';
  }
  const summaryAspect = 'oneC' in entity ? entity.oneC : undefined;
  const metadataKindLabel = customProperty(entity, 'metadataKindLabel');
  return summaryAspect?.objectKind
    || aspects?.oneCObjectProperties?.objectKind
    || metadataKindLabel
    || metadataKind(entity)
    || entity.subTypes?.typeNames?.[0]
    || 'Dataset';
}

function datahubEntityUrl(urn: string): string {
  const path = `/dataset/${encodeURIComponent(urn)}`;
  if (window.location.port === '3002') {
    return `http://localhost:9002${path}`;
  }
  return path;
}

function boolText(value: boolean | undefined): string {
  if (value === undefined) {
    return 'No data';
  }
  return value ? 'Yes' : 'No';
}

function copyText(value: string): void {
  void navigator.clipboard?.writeText(value);
}

function groupRelationships(relationships: Relationship[]): Record<string, Relationship[]> {
  return relationships.reduce<Record<string, Relationship[]>>((acc, relationship) => {
    acc[relationship.type] = acc[relationship.type] ?? [];
    acc[relationship.type].push(relationship);
    return acc;
  }, {});
}

function PropertyRow({ label, value }: { label: string; value?: React.ReactNode }) {
  if (value === undefined || value === null || value === '') {
    return null;
  }
  return (
    <div className="property-row">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  );
}

function LoadingBlock({ label }: { label: string }) {
  return (
    <div className="loading-block">
      <span className="spinner" />
      <span>{label}</span>
    </div>
  );
}

interface ObjectTreeNode {
  id: string;
  label: string;
  secondary?: string;
  kind?: string;
  entity?: OneCDatasetSummary;
  children: ObjectTreeNode[];
  count: number;
}

interface ObjectCategory {
  key: string;
  label: string;
  order: number;
}

const CATEGORY_BY_PREFIX: Record<string, ObjectCategory> = {
  Constant: { key: 'constants', label: 'Constants', order: 5 },
  'Константа': { key: 'constants', label: 'Constants', order: 5 },
  Document: { key: 'documents', label: 'Documents', order: 10 },
  'Документ': { key: 'documents', label: 'Documents', order: 10 },
  Catalog: { key: 'catalogs', label: 'Catalogs', order: 20 },
  'Справочник': { key: 'catalogs', label: 'Catalogs', order: 20 },
  ChartOfCharacteristicTypes: { key: 'charts-of-characteristic-types', label: 'Charts of characteristic types', order: 30 },
  'ПланВидовХарактеристик': { key: 'charts-of-characteristic-types', label: 'Charts of characteristic types', order: 30 },
  ChartOfAccounts: { key: 'charts-of-accounts', label: 'Charts of accounts', order: 40 },
  'ПланСчетов': { key: 'charts-of-accounts', label: 'Charts of accounts', order: 40 },
  ChartOfCalculationTypes: { key: 'charts-of-calculation-types', label: 'Charts of calculation types', order: 50 },
  'ПланВидовРасчета': { key: 'charts-of-calculation-types', label: 'Charts of calculation types', order: 50 },
  InformationRegister: { key: 'information-registers', label: 'Information registers', order: 60 },
  'РегистрСведений': { key: 'information-registers', label: 'Information registers', order: 60 },
  AccumulationRegister: { key: 'accumulation-registers', label: 'Accumulation registers', order: 70 },
  'РегистрНакопления': { key: 'accumulation-registers', label: 'Accumulation registers', order: 70 },
  AccountingRegister: { key: 'accounting-registers', label: 'Accounting registers', order: 80 },
  'РегистрБухгалтерии': { key: 'accounting-registers', label: 'Accounting registers', order: 80 },
  CalculationRegister: { key: 'calculation-registers', label: 'Calculation registers', order: 90 },
  'РегистрРасчета': { key: 'calculation-registers', label: 'Calculation registers', order: 90 },
  Enum: { key: 'enums', label: 'Enumerations', order: 95 },
  'Перечисление': { key: 'enums', label: 'Enumerations', order: 95 },
  TabularSection: { key: 'tabular-sections', label: 'Tabular sections', order: 96 },
  'ТабличнаяЧасть': { key: 'tabular-sections', label: 'Tabular sections', order: 96 },
};

const OTHER_CATEGORY: ObjectCategory = { key: 'other', label: 'Other objects', order: 100 };
const CHART_KINDS_WITHOUT_CATALOG_DETAILS = new Set([
  'ChartOfAccounts',
  'ChartOfCalculationTypes',
  'ПланСчетов',
  'ПланВидовРасчета',
  'Chart of Accounts',
  'Chart of Calculation Types',
]);
const CATALOG_KINDS_WITHOUT_LENGTH_DETAILS = new Set([
  ...CHART_KINDS_WITHOUT_CATALOG_DETAILS,
  'Catalog',
  'Catalogs',
  'Справочник',
  'Справочники',
]);

function canonicalName(entity: DatasetRef): string {
  return customProperty(entity, 'canonicalFullName')
    || entity.properties?.qualifiedName
    || entity.properties?.name
    || entity.name
    || entity.urn;
}

function treeEntityKey(entity: DatasetRef): string {
  return `${infobaseName(entity)}:${canonicalName(entity)}`;
}

function objectPathParts(entity: DatasetRef): string[] {
  return canonicalName(entity).split('.').filter(Boolean);
}

function categoryFor(entity: DatasetRef): ObjectCategory {
  const kindFromMetadata = metadataKind(entity);
  if (kindFromMetadata && CATEGORY_BY_PREFIX[kindFromMetadata]) {
    return CATEGORY_BY_PREFIX[kindFromMetadata];
  }

  const root = objectPathParts(entity)[0];
  if (root && CATEGORY_BY_PREFIX[root]) {
    return CATEGORY_BY_PREFIX[root];
  }

  const kind = objectKind(entity);
  if (kind.includes('Document') || kind.includes('Документ')) {
    return CATEGORY_BY_PREFIX.Document;
  }
  if (kind.includes('Catalog') || kind.includes('Справочник')) {
    return CATEGORY_BY_PREFIX.Catalog;
  }
  if (kind.includes('AccumulationRegister') || kind.includes('РегистрНакопления')) {
    return CATEGORY_BY_PREFIX.AccumulationRegister;
  }

  return OTHER_CATEGORY;
}

function parentCanonicalName(entity: DatasetRef): string | undefined {
  const parts = objectPathParts(entity);
  if (parts.length < 3) {
    return undefined;
  }
  return parts.slice(0, -1).join('.');
}

function sortByDisplayName<T extends DatasetRef>(items: T[]): T[] {
  return [...items].sort((a, b) => displayName(a).localeCompare(displayName(b), 'ru'));
}

function appendUniqueByUrn(
  current: OneCDatasetSummary[],
  nextPage: OneCDatasetSummary[],
): OneCDatasetSummary[] {
  const seen = new Set(current.map((item) => item.urn));
  const appended = nextPage.filter((item) => {
    if (seen.has(item.urn)) {
      return false;
    }
    seen.add(item.urn);
    return true;
  });
  return [...current, ...appended];
}

function flattenSearchValues(values: unknown[]): string[] {
  return values.flatMap((value) => {
    if (Array.isArray(value)) {
      return flattenSearchValues(value);
    }
    if (value === undefined || value === null || value === '') {
      return [];
    }
    return [String(value)];
  });
}

function buildObjectTree(objects: OneCDatasetSummary[]): ObjectTreeNode[] {
  const byCanonical = new Map<string, OneCDatasetSummary>();
  for (const item of objects) {
    byCanonical.set(treeEntityKey(item), item);
  }

  const childrenByParent = new Map<string, OneCDatasetSummary[]>();
  const rootObjects: OneCDatasetSummary[] = [];

  for (const item of objects) {
    const parentKey = parentCanonicalName(item);
    const parentTreeKey = parentKey ? `${infobaseName(item)}:${parentKey}` : undefined;
    if (parentTreeKey && byCanonical.has(parentTreeKey)) {
      childrenByParent.set(parentTreeKey, [...(childrenByParent.get(parentTreeKey) ?? []), item]);
    } else {
      rootObjects.push(item);
    }
  }

  const makeEntityNode = (entity: OneCDatasetSummary): ObjectTreeNode => {
    const childNodes = sortByDisplayName(childrenByParent.get(treeEntityKey(entity)) ?? [])
      .map(makeEntityNode);
    return {
      id: `entity:${entity.urn}`,
      label: displayName(entity),
      secondary: customProperty(entity, 'canonicalFullName') || entity.urn,
      kind: objectKind(entity),
      entity,
      children: childNodes,
      count: 1 + childNodes.reduce((sum, child) => sum + child.count, 0),
    };
  };

  const infobaseGroups = new Map<string, Map<string, { category: ObjectCategory; nodes: ObjectTreeNode[] }>>();

  for (const item of sortByDisplayName(rootObjects)) {
    const infobase = infobaseName(item);
    const category = categoryFor(item);
    const categories = infobaseGroups.get(infobase) ?? new Map<string, { category: ObjectCategory; nodes: ObjectTreeNode[] }>();
    const group = categories.get(category.key) ?? { category, nodes: [] };
    group.nodes.push(makeEntityNode(item));
    categories.set(category.key, group);
    infobaseGroups.set(infobase, categories);
  }

  return Array.from(infobaseGroups.entries())
    .sort(([a], [b]) => a.localeCompare(b, 'ru'))
    .map(([infobase, categories]) => {
      const categoryNodes = Array.from(categories.values())
        .sort((a, b) => a.category.order - b.category.order || a.category.label.localeCompare(b.category.label, 'ru'))
        .map(({ category, nodes }) => ({
          id: `category:${infobase}:${category.key}`,
          label: category.label,
          children: nodes,
          count: nodes.reduce((sum, child) => sum + child.count, 0),
        }));
      return {
        id: `infobase:${infobase}`,
        label: infobase,
        kind: 'Infobase',
        children: categoryNodes,
        count: categoryNodes.reduce((sum, child) => sum + child.count, 0),
      };
    });
}

function findNodePath(nodes: ObjectTreeNode[], selectedUrn?: string): string[] {
  if (!selectedUrn) {
    return [];
  }

  for (const node of nodes) {
    if (node.entity?.urn === selectedUrn) {
      return [node.id];
    }
    const childPath = findNodePath(node.children, selectedUrn);
    if (childPath.length > 0) {
      return [node.id, ...childPath];
    }
  }

  return [];
}

function TreeNodeRow({
  node,
  depth,
  expandedNodeIds,
  searchActive,
  selectedUrn,
  onSelect,
  onToggle,
}: {
  node: ObjectTreeNode;
  depth: number;
  expandedNodeIds: Set<string>;
  searchActive: boolean;
  selectedUrn?: string;
  onSelect: (urn: string) => void;
  onToggle: (nodeId: string) => void;
}) {
  const hasChildren = node.children.length > 0;
  const expanded = searchActive || expandedNodeIds.has(node.id);
  const selected = node.entity?.urn === selectedUrn;
  const Icon = node.entity
    ? (objectKind(node.entity) === 'ТабличнаяЧасть' || objectKind(node.entity) === 'Tabular Section' ? Table2 : FileText)
    : node.kind === 'Infobase' ? Database : Folder;

  return (
    <li>
      <div className="tree-row" style={{ '--tree-depth': depth } as React.CSSProperties}>
        {hasChildren ? (
          <button className="tree-toggle" type="button" onClick={() => onToggle(node.id)} title={expanded ? 'Collapse' : 'Expand'}>
            {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          </button>
        ) : (
          <span className="tree-toggle-spacer" />
        )}
        <button
          className={`tree-node-action ${selected ? 'selected' : ''}`}
          type="button"
          onClick={() => (node.entity ? onSelect(node.entity.urn) : onToggle(node.id))}
        >
          <span className="tree-node-icon" aria-hidden><Icon size={17} /></span>
          <span className="tree-node-main">
            <strong>{node.label}</strong>
            {node.secondary && <small>{node.secondary}</small>}
          </span>
          {hasChildren ? (
            <span className="tree-node-count">{node.count}</span>
          ) : node.kind ? (
            <span className="tree-kind-pill">{node.kind}</span>
          ) : null}
        </button>
      </div>
      {hasChildren && expanded && (
        <ul className="tree-children">
          {node.children.map((child) => (
            <TreeNodeRow
              depth={depth + 1}
              expandedNodeIds={expandedNodeIds}
              key={child.id}
              node={child}
              searchActive={searchActive}
              selectedUrn={selectedUrn}
              onSelect={onSelect}
              onToggle={onToggle}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

function ObjectList({
  objects,
  selectedUrn,
  filters,
  total,
  nextStart,
  loading,
  loadingMore,
  error,
  onSelect,
  onFiltersChange,
  onRefresh,
  onLoadMore,
}: {
  objects: OneCDatasetSummary[];
  selectedUrn?: string;
  filters: ObjectFilterState;
  total: number;
  nextStart: number;
  loading: boolean;
  loadingMore: boolean;
  error?: string;
  onSelect: (urn: string) => void;
  onFiltersChange: (filters: ObjectFilterState) => void;
  onRefresh: () => void;
  onLoadMore: () => void;
}) {
  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<string>>(() => new Set());
  const objectTree = useMemo(() => buildObjectTree(objects), [objects]);
  const searchActive = filters.query.trim().length > 0;
  const hasMore = nextStart < total;

  useEffect(() => {
    const path = findNodePath(objectTree, selectedUrn);
    if (path.length === 0) {
      return;
    }
    setExpandedNodeIds((current) => new Set([...current, ...path]));
  }, [objectTree, selectedUrn]);

  const toggleNode = useCallback((nodeId: string) => {
    setExpandedNodeIds((current) => {
      const next = new Set(current);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }, []);

  return (
    <aside className="object-panel" aria-label="1C objects">
      <div className="panel-title-row">
        <div>
          <h1>1C Metadata Explorer</h1>
          <p>{objects.length} of {total} DataHub datasets loaded</p>
        </div>
        <button className="icon-button" type="button" onClick={onRefresh} title="Refresh list">
          <RefreshCw size={18} />
        </button>
      </div>

      <label className="search-box">
        <Search size={17} />
        <input
          value={filters.query}
          onChange={(event) => onFiltersChange({ query: event.target.value })}
          placeholder="Search by name, synonym, UUID, or URN"
        />
      </label>

      {loading && <LoadingBlock label="Loading 1C objects" />}
      {error && <div className="error-box">{error}</div>}

      <nav className="object-tree" aria-label="1C object tree">
        <ul className="tree-list">
          {objectTree.map((node) => (
            <TreeNodeRow
              depth={0}
              expandedNodeIds={expandedNodeIds}
              key={node.id}
              node={node}
              searchActive={searchActive}
              selectedUrn={selectedUrn}
              onSelect={onSelect}
              onToggle={toggleNode}
            />
          ))}
        </ul>
      </nav>

      {!loading && objectTree.length === 0 && (
        <EmptyState title="No results" detail="Adjust the search query." />
      )}
      {hasMore && (
        <button
          className="load-more-button"
          type="button"
          disabled={loading || loadingMore}
          onClick={onLoadMore}
        >
          {loadingMore ? 'Loading more objects...' : `Load ${Math.min(DEFAULT_SEARCH_PAGE_SIZE, total - nextStart)} more`}
        </button>
      )}
    </aside>
  );
}

function ObjectHeader({ detail, aspects }: { detail: DatasetDetail; aspects: OneCAspects }) {
  const common = aspects.oneCObjectProperties;
  return (
    <header className="detail-header">
      <div className="title-block">
        <span className="eyebrow">{objectKind(detail, aspects)}</span>
        <h2>{common?.fullName || detail.properties?.qualifiedName || detail.name}</h2>
        <p>{detail.properties?.name || detail.urn}</p>
      </div>
      <div className="header-actions">
        <button className="text-button" type="button" onClick={() => copyText(detail.urn)}>
          Copy URN
        </button>
        <a className="icon-link" href={datahubEntityUrl(detail.urn)} target="_blank" rel="noreferrer" title="Open standard DataHub page">
          <ExternalLink size={18} />
        </a>
      </div>
    </header>
  );
}

function PropertiesSection({ detail, aspects }: { detail: DatasetDetail; aspects: OneCAspects }) {
  const objectProps = aspects.oneCObjectProperties;
  const catalog = aspects.oneCCatalogProperties;
  const document = aspects.oneCDocumentProperties;
  const register = aspects.oneCRegisterProperties;
  const kindValues = [
    objectKind(detail, aspects),
    metadataKind(detail),
    detail.subTypes?.typeNames,
  ];
  const hideCatalogDetails = flattenSearchValues(kindValues)
    .some((value) => CHART_KINDS_WITHOUT_CATALOG_DETAILS.has(value));
  const hideCatalogLengthDetails = flattenSearchValues(kindValues)
    .some((value) => CATALOG_KINDS_WITHOUT_LENGTH_DETAILS.has(value));

  return (
    <section className="section">
      <div className="section-heading">
        <FolderTree size={18} />
        <h3>1C properties</h3>
      </div>
      <div className="property-grid">
        <dl>
          <PropertyRow label="Full name" value={objectProps?.fullName || detail.properties?.qualifiedName} />
          <PropertyRow label="Canonical full name" value={customProperty(detail, 'canonicalFullName')} />
          <PropertyRow label="Synonym" value={objectProps?.synonym || detail.properties?.description} />
          <PropertyRow label="Object kind" value={objectProps?.objectKind || detail.subTypes?.typeNames?.join(', ')} />
          <PropertyRow label="Infobase" value={customProperty(detail, 'infobaseName') || objectProps?.configurationName} />
          <PropertyRow label="UUID" value={objectProps?.metadataUuid} />
          <PropertyRow label="Parent UUID" value={objectProps?.parentObjectUuid} />
        </dl>
        <dl>
          {catalog && (
            <>
              {!hideCatalogDetails && <PropertyRow label="Hierarchical" value={boolText(catalog.isHierarchical)} />}
              <PropertyRow label="Hierarchy kind" value={catalog.hierarchyKind} />
              {!hideCatalogDetails && <PropertyRow label="Has owners" value={boolText(catalog.hasOwner)} />}
              <PropertyRow label="Owners" value={catalog.ownerNames?.join(', ')} />
              {!hideCatalogLengthDetails && <PropertyRow label="Code length" value={catalog.codeLength} />}
              {!hideCatalogLengthDetails && <PropertyRow label="Description length" value={catalog.descriptionLength} />}
            </>
          )}
          {document && (
            <>
              <PropertyRow label="Numerator" value={document.numeratorName} />
              <PropertyRow label="Numbering periodicity" value={document.numberingPeriodicity} />
            </>
          )}
          {register && (
            <>
              <PropertyRow label="Register kind" value={register.registerKind} />
              <PropertyRow label="Periodicity" value={register.periodicity} />
              <PropertyRow label="Write mode" value={register.writeMode} />
            </>
          )}
        </dl>
      </div>
    </section>
  );
}

function DbMappingSection({ aspects, relationships }: { aspects: OneCAspects; relationships: Relationship[] }) {
  const mapping = aspects.oneCDbMapping;
  const dbRelationships = relationships.filter((relationship) => relationship.type === 'MapsToDbTable');
  const columns = mapping?.attributeColumns ?? [];

  return (
    <section className="section">
      <div className="section-heading">
        <Database size={18} />
        <h3>1C column mapping</h3>
      </div>
      {!mapping && dbRelationships.length === 0 ? (
        <EmptyState title="Mapping not found" detail="oneCDbMapping is not emitted for totals tables and objects without a direct physical DB analogue." />
      ) : (
        <>
          <div className="pg-summary">
            <div>
              <span>Physical DB table</span>
              <strong>{mapping?.dbTableName || 'No oneCDbMapping'}</strong>
            </div>
            <div>
              <span>Linked DB datasets</span>
              <strong>{dbRelationships.length}</strong>
            </div>
          </div>
          {dbRelationships.map((relationship) => (
            <EntityLinkRow key={`${relationship.type}-${relationship.entity?.urn}`} entity={relationship.entity} />
          ))}
          {columns.length > 0 && (
            <MappingTable rows={columns} />
          )}
        </>
      )}
    </section>
  );
}

function MappingTable({ rows }: { rows: AttributeColumnMapping[] }) {
  return (
    <div className="table-wrap table-wrap-scroll" tabIndex={0}>
      <table>
        <thead>
          <tr>
            <th>1C attribute</th>
            <th>FieldPath</th>
            <th>DB column</th>
            <th>Role</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.attributeFieldPath}-${row.dbColumnName}-${index}`}>
              <td>{row.attributeName}</td>
              <td><code>{row.attributeFieldPath}</code></td>
              <td><code>{row.dbColumnName}</code></td>
              <td><span className="role-pill">{row.columnRole}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function aspectUrnsFor(
  aspectRelationships: OneCDomainRelationships | undefined,
  relationshipType: OneCRelationshipType,
): string[] {
  const field = RELATIONSHIP_ASPECT_FIELDS[relationshipType];
  return aspectRelationships?.[field] ?? [];
}

function RelationshipsSection({
  relationships,
  aspectRelationships,
}: {
  relationships: Relationship[];
  aspectRelationships?: OneCDomainRelationships;
}) {
  const grouped = groupRelationships(relationships);
  const groups = Object.entries(RELATIONSHIP_LABELS)
    .map(([type, label]) => {
      const relationshipType = type as OneCRelationshipType;
      const items = grouped[type] ?? [];
      const resolvedUrns = new Set(items.map((item) => item.entity?.urn).filter(Boolean));
      const aspectUrns = aspectUrnsFor(aspectRelationships, relationshipType);
      const unresolvedAspectUrns = aspectUrns.filter((urn) => !resolvedUrns.has(urn));
      return { type: relationshipType, label, items, aspectUrns, unresolvedAspectUrns };
    })
    .filter((group) => group.items.length > 0 || group.unresolvedAspectUrns.length > 0);

  return (
    <section className="section">
      <div className="section-heading">
        <Network size={18} />
        <h3>Domain relationships</h3>
      </div>
      {groups.length === 0 ? (
        <EmptyState title="No relationships found" detail="The graph relationship index did not return domain relationships for the selected entity." />
      ) : (
        <div className="relationship-grid">
          {groups.map((group) => (
            <div className="relationship-group" key={group.type}>
              <div className="relationship-group-title">
                <strong>{group.label}</strong>
                <span>{group.items.length + group.unresolvedAspectUrns.length}</span>
              </div>
              {group.unresolvedAspectUrns.length > 0 && (
                <div className="relationship-aspect-note">
                  {group.items.length > 0
                    ? 'Some relationships are shown from the aspect payload because the graph index did not return the entity.'
                    : 'Relationships are shown from the aspect payload because the graph index did not return the entity.'}
                </div>
              )}
              {group.items.map((relationship) => (
                <EntityLinkRow key={`${group.type}-${relationship.entity?.urn}`} entity={relationship.entity} />
              ))}
              {group.unresolvedAspectUrns.map((urn) => (
                <RawUrnLinkRow key={`${group.type}-${urn}`} urn={urn} />
              ))}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function SchemaSection({ fields }: { fields: SchemaField[] }) {
  return (
    <section className="section">
      <div className="section-heading">
        <Table2 size={18} />
        <h3>Attributes and fields</h3>
      </div>
      {fields.length === 0 ? (
        <EmptyState title="SchemaMetadata is empty" detail="No attribute list was found for the selected entity." />
      ) : (
        <div className="table-wrap table-wrap-scroll" tabIndex={0}>
          <table>
            <thead>
              <tr>
                <th>Field</th>
                <th>Label</th>
                <th>DataHub type</th>
                <th>1C type</th>
              </tr>
            </thead>
            <tbody>
              {fields.map((field) => (
                <tr key={field.fieldPath}>
                  <td><code>{field.fieldPath}</code></td>
                  <td>{field.label || field.description || 'No description'}</td>
                  <td>{field.type}</td>
                  <td>{field.nativeDataType || 'No data'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function EntityLinkRow({ entity }: { entity?: DatasetRef | null }) {
  if (!entity) {
    return <div className="entity-link-row muted-row">Entity was not resolved by the graph index</div>;
  }

  return (
    <a className="entity-link-row" href={datahubEntityUrl(entity.urn)} target="_blank" rel="noreferrer">
      <span>
        <strong>{displayName(entity)}</strong>
        <small>{secondaryName(entity)}</small>
      </span>
      <ExternalLink size={15} />
    </a>
  );
}

function RawUrnLinkRow({ urn }: { urn: string }) {
  return (
    <a className="entity-link-row raw-urn-row" href={datahubEntityUrl(urn)} target="_blank" rel="noreferrer">
      <span>
        <strong>{urn}</strong>
        <small>URN from oneCDomainRelationships</small>
      </span>
      <ExternalLink size={15} />
    </a>
  );
}

function DetailPanel({
  detail,
  loading,
  error,
}: {
  detail?: DatasetDetail;
  loading: boolean;
  error?: string;
}) {
  const aspects = useMemo(() => parseOneCAspects(detail?.aspects), [detail?.aspects]);
  const relationships = detail?.relationships?.relationships ?? [];
  const fields = detail?.schemaMetadata?.fields ?? [];

  if (loading) {
    return (
      <main className="detail-panel">
        <LoadingBlock label="Loading object properties" />
      </main>
    );
  }

  if (error) {
    return (
      <main className="detail-panel">
        <div className="error-box">{error}</div>
      </main>
    );
  }

  if (!detail) {
    return (
      <main className="detail-panel">
        <EmptyState title="Select an object" detail="1C datasets from DataHub are shown on the left. Details will open here." />
      </main>
    );
  }

  return (
    <main className="detail-panel">
      <ObjectHeader detail={detail} aspects={aspects} />
      <div className="detail-sections">
        <PropertiesSection detail={detail} aspects={aspects} />
        <DbMappingSection aspects={aspects} relationships={relationships} />
        <RelationshipsSection
          relationships={relationships}
          aspectRelationships={aspects.oneCDomainRelationships}
        />
        <SchemaSection fields={fields} />
      </div>
    </main>
  );
}

export const App: React.FC = () => {
  const [objects, setObjects] = useState<OneCDatasetSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [nextStart, setNextStart] = useState(0);
  const [selectedUrn, setSelectedUrn] = useState<string | undefined>(getInitialUrn);
  const [detail, setDetail] = useState<DatasetDetail | undefined>();
  const [filters, setFilters] = useState<ObjectFilterState>({ query: '' });
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [listLoading, setListLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [listError, setListError] = useState<string | undefined>();
  const [detailError, setDetailError] = useState<string | undefined>();
  const nextStartRef = useRef(0);
  const listRequestId = useRef(0);
  const detailRequestId = useRef(0);
  const initialSelectedUrn = useRef(selectedUrn);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setDebouncedQuery(filters.query);
    }, 300);
    return () => window.clearTimeout(timeoutId);
  }, [filters.query]);

  const loadObjectsForQuery = useCallback(async (query: string, append = false) => {
    const requestId = listRequestId.current + 1;
    listRequestId.current = requestId;
    const start = append ? nextStartRef.current : 0;

    if (!append) {
      setObjects([]);
      setTotal(0);
      setNextStart(0);
      nextStartRef.current = 0;
    }
    setListLoading(!append);
    setLoadingMore(append);
    setListError(undefined);
    try {
      const response = await searchOneCDatasets(query, start, DEFAULT_SEARCH_PAGE_SIZE);
      if (requestId !== listRequestId.current) {
        return;
      }
      setObjects((current) => (append ? appendUniqueByUrn(current, response.results) : response.results));
      setTotal(response.total);
      const newNextStart = start + response.results.length;
      nextStartRef.current = newNextStart;
      setNextStart(newNextStart);
      if (!append) {
        const resultUrns = new Set(response.results.map((item) => item.urn));
        setSelectedUrn((current) => {
          if (current && resultUrns.has(current)) {
            return current;
          }
          if (current && current === initialSelectedUrn.current && query.trim() === '') {
            return current;
          }
          return response.results[0]?.urn;
        });
      }
    } catch (error) {
      if (requestId !== listRequestId.current) {
        return;
      }
      setListError(error instanceof Error ? error.message : String(error));
    } finally {
      if (requestId === listRequestId.current) {
        setListLoading(false);
        setLoadingMore(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadObjectsForQuery(debouncedQuery, false);
  }, [debouncedQuery, loadObjectsForQuery]);

  useEffect(() => {
    if (!selectedUrn) {
      detailRequestId.current += 1;
      setDetail(undefined);
      setDetailError(undefined);
      setDetailLoading(false);
      return;
    }
    const requestId = detailRequestId.current + 1;
    detailRequestId.current = requestId;
    updateUrnParam(selectedUrn);
    setDetail(undefined);
    setDetailLoading(true);
    setDetailError(undefined);
    fetchOneCDatasetDetail(selectedUrn)
      .then((datasetDetail) => {
        if (requestId === detailRequestId.current) {
          setDetail(datasetDetail);
        }
      })
      .catch((error) => {
        if (requestId === detailRequestId.current) {
          setDetail(undefined);
          setDetailError(error instanceof Error ? error.message : String(error));
        }
      })
      .finally(() => {
        if (requestId === detailRequestId.current) {
          setDetailLoading(false);
        }
      });
  }, [selectedUrn]);

  const refreshObjects = useCallback(() => {
    if (filters.query === debouncedQuery) {
      void loadObjectsForQuery(debouncedQuery, false);
      return;
    }
    setDebouncedQuery(filters.query);
  }, [debouncedQuery, filters.query, loadObjectsForQuery]);

  return (
    <div className="app-shell">
      <ObjectList
        objects={objects}
        selectedUrn={selectedUrn}
        filters={filters}
        total={total}
        nextStart={nextStart}
        loading={listLoading}
        loadingMore={loadingMore}
        error={listError}
        onSelect={setSelectedUrn}
        onFiltersChange={setFilters}
        onRefresh={refreshObjects}
        onLoadMore={() => void loadObjectsForQuery(debouncedQuery, true)}
      />
      <DetailPanel detail={detail} loading={detailLoading} error={detailError} />
    </div>
  );
};

export default App;
