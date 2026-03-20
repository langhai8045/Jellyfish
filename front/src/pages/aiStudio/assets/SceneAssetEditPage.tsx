import { useNavigate, useParams } from 'react-router-dom'
import { AssetEditPageBase } from './components/AssetEditPageBase'
import { assetAdapters } from './assetAdapters'

export default function SceneAssetEditPage() {
  const navigate = useNavigate()
  const { sceneId } = useParams<{ sceneId: string }>()
  const adapter = assetAdapters.scene

  return (
    <AssetEditPageBase<any, any>
      assetId={sceneId}
      onNavigate={(to, replace) => navigate(to, replace ? { replace: true } : undefined)}
      {...adapter}
    />
  )
}

