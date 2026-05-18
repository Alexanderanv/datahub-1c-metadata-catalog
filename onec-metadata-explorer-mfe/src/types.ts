export const ONEC_PLATFORM_URN = 'urn:li:dataPlatform:1c-enterprise';

export const ONEC_ASPECT_NAMES = [
  'oneCObjectProperties',
  'oneCCatalogProperties',
  'oneCDocumentProperties',
  'oneCRegisterProperties',
  'oneCDbMapping',
  'oneCDomainRelationships',
] as const;

export const ONEC_RELATIONSHIP_TYPES = [
  'HasTabularPart',
  'IsTabularPartOf',
  'MapsToDbTable',
  'RefersToObject',
  'IsReferencedByObject',
] as const;

export type OneCAspectName = typeof ONEC_ASPECT_NAMES[number];
export type OneCRelationshipType = typeof ONEC_RELATIONSHIP_TYPES[number];

export interface CustomProperty {
  key: string;
  value: string;
}

export interface DatasetProperties {
  name: string;
  qualifiedName?: string | null;
  description?: string | null;
  customProperties?: CustomProperty[] | null;
}

export interface SubTypes {
  typeNames?: string[] | null;
}

export interface DatasetRef {
  urn: string;
  type: string;
  name?: string | null;
  properties?: DatasetProperties | null;
  subTypes?: SubTypes | null;
}

export interface SchemaField {
  fieldPath: string;
  label?: string | null;
  description?: string | null;
  type: string;
  nativeDataType?: string | null;
  nullable: boolean;
}

export interface RawAspect {
  aspectName: OneCAspectName | string;
  payload?: string | null;
}

export interface Relationship {
  type: OneCRelationshipType | string;
  direction: 'INCOMING' | 'OUTGOING';
  entity?: DatasetRef | null;
}

export interface OneCObjectProperties {
  objectKind?: string;
  fullName?: string;
  synonym?: string;
  comment?: string;
  configurationName?: string;
  metadataUuid?: string;
  parentObjectUuid?: string;
  attributesUuidMap?: Record<string, string>;
}

export interface OneCCatalogProperties {
  isHierarchical?: boolean;
  hierarchyKind?: string;
  hasOwner?: boolean;
  ownerNames?: string[];
  codeLength?: number;
  descriptionLength?: number;
}

export interface OneCDocumentProperties {
  isPostable?: boolean;
  numeratorName?: string;
  numberingPeriodicity?: string;
  numberLength?: number;
}

export interface OneCRegisterProperties {
  registerKind?: string;
  periodicity?: string;
  writeMode?: string;
  totalsEnabled?: boolean;
}

export interface AttributeColumnMapping {
  attributeName: string;
  attributeFieldPath: string;
  dbColumnName: string;
  columnRole: string;
}

export interface OneCDbMapping {
  dbTableName?: string;
  attributeColumns?: AttributeColumnMapping[];
}

export interface OneCDomainRelationships {
  hasTabularPart?: string[];
  isTabularPartOf?: string[];
  mapsToDbTable?: string[];
  refersToObject?: string[];
  isReferencedByObject?: string[];
}

export interface OneCAspects {
  oneCObjectProperties?: OneCObjectProperties;
  oneCCatalogProperties?: OneCCatalogProperties;
  oneCDocumentProperties?: OneCDocumentProperties;
  oneCRegisterProperties?: OneCRegisterProperties;
  oneCDbMapping?: OneCDbMapping;
  oneCDomainRelationships?: OneCDomainRelationships;
}

export interface OneCDatasetSummary extends DatasetRef {
  oneC?: OneCObjectProperties;
  aspects?: RawAspect[] | null;
}

export interface DatasetDetail extends DatasetRef {
  schemaMetadata?: {
    fields?: SchemaField[] | null;
  } | null;
  aspects?: RawAspect[] | null;
  relationships?: {
    total?: number | null;
    relationships?: Relationship[] | null;
  } | null;
  siblings?: {
    isPrimary?: boolean | null;
    siblings?: DatasetRef[] | null;
  } | null;
}

export interface ObjectFilterState {
  query: string;
}
