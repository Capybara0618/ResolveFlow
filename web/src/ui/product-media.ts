import collection from '../../../fixtures/catalog/collection-v1.json'

/** Exact product + variant match: shared legacy asset keys are not product identities. */
export function productImage(asset: string, name: string, variant?: string) {
  const product = collection.products.find(p => p.asset_key === asset && p.name === name)
  const sku = variant === undefined ? product?.skus[0] : product?.skus.find(s => s.variant === variant)
  return sku ? { src: `/products/v1/${sku.image}.webp`, variant: sku.variant } : null
}
