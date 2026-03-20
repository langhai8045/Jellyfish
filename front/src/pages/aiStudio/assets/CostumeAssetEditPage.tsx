import { useNavigate, useParams } from 'react-router-dom'
import { AssetEditPageBase } from './components/AssetEditPageBase'
import { assetAdapters } from './assetAdapters'

export default function CostumeAssetEditPage() {
  const navigate = useNavigate()
  const { costumeId } = useParams<{ costumeId: string }>()
  const adapter = assetAdapters.costume

  return (
    <AssetEditPageBase<any, any>
      assetId={costumeId}
      onNavigate={(to, replace) => navigate(to, replace ? { replace: true } : undefined)}
      {...adapter}
    />
  )
}

