import {
  DatasetDetail,
  ONEC_ASPECT_NAMES,
  ONEC_PLATFORM_URN,
  ONEC_RELATIONSHIP_TYPES,
  OneCAspects,
  OneCDatasetSummary,
  RawAspect,
  Relationship,
} from './types';

interface GraphqlResponse<T> {
  data?: T;
  errors?: Array<{ message: string }>;
}

const GRAPHQL_ENDPOINTS = ['/api/graphql', '/api/v2/graphql'];
export const DEFAULT_SEARCH_PAGE_SIZE = 100;
const RELATIONSHIP_PAGE_SIZE = 500;

const DATASET_CARD_FRAGMENT = `
  urn
  type
  ... on Dataset {
    name
    properties {
      name
      qualifiedName
      description
      customProperties {
        key
        value
      }
    }
    subTypes {
      typeNames
    }
  }
`;

const ONEC_ASPECT_SELECTION = ONEC_ASPECT_NAMES.map((name) => `"${name}"`).join(', ');
const ONEC_RELATIONSHIP_SELECTION = ONEC_RELATIONSHIP_TYPES.map((name) => `"${name}"`).join(', ');

const SEARCH_DATASETS_QUERY = `
  query SearchOneCDatasets($query: String!, $start: Int!, $count: Int!) {
    search(
      input: {
        type: DATASET
        query: $query
        start: $start
        count: $count
        orFilters: [
          {
            and: [
              { field: "platform", values: ["${ONEC_PLATFORM_URN}"] }
            ]
          }
        ]
      }
    ) {
      total
      searchResults {
        entity {
          ${DATASET_CARD_FRAGMENT}
        }
      }
    }
  }
`;

const DATASET_DETAIL_QUERY = `
  query OneCDatasetDetail($urn: String!, $relationshipStart: Int!, $relationshipCount: Int!) {
    dataset(urn: $urn) {
      ${DATASET_CARD_FRAGMENT}
      schemaMetadata {
        fields {
          fieldPath
          label
          description
          type
          nativeDataType
          nullable
        }
      }
      aspects(input: { aspectNames: [${ONEC_ASPECT_SELECTION}] }) {
        aspectName
        payload
      }
      relationships(
        input: {
          types: [${ONEC_RELATIONSHIP_SELECTION}]
          direction: OUTGOING
          start: $relationshipStart
          count: $relationshipCount
        }
      ) {
        total
        relationships {
          type
          direction
          entity {
            ${DATASET_CARD_FRAGMENT}
          }
        }
      }
      siblings {
        isPrimary
        siblings {
          urn
          type
          ... on Dataset {
            name
            properties {
              name
              qualifiedName
              description
            }
            subTypes {
              typeNames
            }
          }
        }
      }
    }
  }
`;

const DATASET_RELATIONSHIPS_QUERY = `
  query OneCDatasetRelationships($urn: String!, $start: Int!, $count: Int!) {
    dataset(urn: $urn) {
      relationships(
        input: {
          types: [${ONEC_RELATIONSHIP_SELECTION}]
          direction: OUTGOING
          start: $start
          count: $count
        }
      ) {
        total
        relationships {
          type
          direction
          entity {
            ${DATASET_CARD_FRAGMENT}
          }
        }
      }
    }
  }
`;

async function graphqlRequest<T>(query: string, variables: Record<string, unknown>): Promise<T> {
  let lastError: Error | undefined;

  for (const endpoint of GRAPHQL_ENDPOINTS) {
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query, variables }),
      });

      if (!response.ok) {
        throw new Error(`${endpoint} returned HTTP ${response.status}`);
      }

      const body = (await response.json()) as GraphqlResponse<T>;
      if (body.errors?.length) {
        throw new Error(body.errors.map((error) => error.message).join('; '));
      }
      if (!body.data) {
        throw new Error(`${endpoint} returned empty data`);
      }
      return body.data;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
    }
  }

  throw lastError ?? new Error('DataHub GraphQL request failed');
}

function parseAspectPayload<T>(aspect: RawAspect): T | undefined {
  if (!aspect.payload) {
    return undefined;
  }

  try {
    return JSON.parse(aspect.payload) as T;
  } catch {
    return undefined;
  }
}

export function parseOneCAspects(rawAspects?: RawAspect[] | null): OneCAspects {
  const aspects: OneCAspects = {};

  for (const aspect of rawAspects ?? []) {
    switch (aspect.aspectName) {
      case 'oneCObjectProperties':
        aspects.oneCObjectProperties = parseAspectPayload(aspect);
        break;
      case 'oneCCatalogProperties':
        aspects.oneCCatalogProperties = parseAspectPayload(aspect);
        break;
      case 'oneCDocumentProperties':
        aspects.oneCDocumentProperties = parseAspectPayload(aspect);
        break;
      case 'oneCRegisterProperties':
        aspects.oneCRegisterProperties = parseAspectPayload(aspect);
        break;
      case 'oneCDbMapping':
        aspects.oneCDbMapping = parseAspectPayload(aspect);
        break;
      case 'oneCDomainRelationships':
        aspects.oneCDomainRelationships = parseAspectPayload(aspect);
        break;
      default:
        break;
    }
  }

  return aspects;
}

export async function searchOneCDatasets(
  query: string,
  start = 0,
  count = DEFAULT_SEARCH_PAGE_SIZE,
): Promise<{ total: number; results: OneCDatasetSummary[] }> {
  const normalizedQuery = query.trim() || '*';
  const data = await graphqlRequest<{
    search: {
      total: number;
      searchResults: Array<{ entity: OneCDatasetSummary }>;
    };
  }>(SEARCH_DATASETS_QUERY, {
    query: normalizedQuery,
    start,
    count,
  });

  return {
    total: data.search.total,
    results: data.search.searchResults.map(({ entity }) => entity),
  };
}

export async function fetchOneCDatasetDetail(urn: string): Promise<DatasetDetail> {
  const data = await graphqlRequest<{ dataset: DatasetDetail | null }>(DATASET_DETAIL_QUERY, {
    urn,
    relationshipStart: 0,
    relationshipCount: RELATIONSHIP_PAGE_SIZE,
  });

  if (!data.dataset) {
    throw new Error('Dataset not found');
  }

  const firstPage = data.dataset.relationships;
  const relationships = [...(firstPage?.relationships ?? [])];
  const total = firstPage?.total ?? relationships.length;

  while (relationships.length < total) {
    const page = await fetchRelationshipPage(urn, relationships.length, RELATIONSHIP_PAGE_SIZE);
    const pageRelationships = page.relationships ?? [];
    if (pageRelationships.length === 0) {
      break;
    }
    relationships.push(...pageRelationships);
  }

  data.dataset.relationships = {
    total,
    relationships,
  };

  return data.dataset;
}

async function fetchRelationshipPage(
  urn: string,
  start: number,
  count: number,
): Promise<{ total?: number | null; relationships?: Relationship[] | null }> {
  const data = await graphqlRequest<{
    dataset: {
      relationships?: {
        total?: number | null;
        relationships?: Relationship[] | null;
      } | null;
    } | null;
  }>(DATASET_RELATIONSHIPS_QUERY, { urn, start, count });

  if (!data.dataset) {
    throw new Error('Dataset not found while loading relationships');
  }

  return data.dataset.relationships ?? {};
}
