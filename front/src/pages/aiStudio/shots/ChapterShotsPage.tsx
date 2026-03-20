import { useEffect, useMemo, useState } from 'react'
import { Button, Card, Empty, Input, List, Select, Space, Spin, message } from 'antd'
import type { ShotRead, ShotStatus } from '../../../services/generated'
import { StudioShotsService } from '../../../services/generated'
import { useParams } from 'react-router-dom'

const { TextArea } = Input

type ShotDraft = {
  title: string
  script_excerpt: string
  status?: ShotStatus
}

export function ChapterShotsPage() {
  const { chapterId } = useParams<{ projectId: string; chapterId: string }>()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [shots, setShots] = useState<ShotRead[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<ShotDraft | null>(null)

  const selectedShot = useMemo(() => shots.find((s) => s.id === selectedId) ?? null, [selectedId, shots])

  const refresh = async () => {
    if (!chapterId) return
    setLoading(true)
    try {
      const res = await StudioShotsService.listShotsApiV1StudioShotsGet({
        chapterId,
        page: 1,
        pageSize: 100,
        order: 'index',
        isDesc: false,
      })
      const items = res.data?.items ?? []
      setShots(items)
      if (!selectedId && items.length > 0) setSelectedId(items[0].id)
    } catch {
      message.error('加载分镜失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapterId])

  useEffect(() => {
    if (!selectedShot) {
      setDraft(null)
      return
    }
    setDraft({
      title: selectedShot.title ?? '',
      script_excerpt: selectedShot.script_excerpt ?? '',
      status: selectedShot.status ?? undefined,
    })
  }, [selectedShot])

  const dirty = useMemo(() => {
    if (!selectedShot || !draft) return false
    return (
      (selectedShot.title ?? '') !== draft.title ||
      (selectedShot.script_excerpt ?? '') !== draft.script_excerpt ||
      (selectedShot.status ?? undefined) !== draft.status
    )
  }, [draft, selectedShot])

  const save = async () => {
    if (!selectedShot || !draft) return
    setSaving(true)
    try {
      const res = await StudioShotsService.updateShotApiV1StudioShotsShotIdPatch({
        shotId: selectedShot.id,
        requestBody: {
          title: draft.title,
          script_excerpt: draft.script_excerpt,
          status: draft.status ?? null,
        },
      })
      const next = res.data
      if (next) {
        setShots((prev) => prev.map((s) => (s.id === next.id ? next : s)))
        message.success('已保存')
      }
    } catch {
      message.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const cancel = () => {
    if (!selectedShot) return
    setDraft({
      title: selectedShot.title ?? '',
      script_excerpt: selectedShot.script_excerpt ?? '',
      status: selectedShot.status ?? undefined,
    })
  }

  return (
    <Card title="分镜" style={{ padding: 0 }}>
      <div className="flex gap-3 h-full min-h-0" style={{ height: 'calc(100vh - 170px)' }}>
        <div
          className="shrink-0 min-w-0"
          style={{
            width: 320,
            borderRight: '1px solid rgba(0,0,0,0.06)',
            paddingRight: 12,
            overflow: 'auto',
          }}
        >
          {loading ? (
            <div className="py-10 flex justify-center">
              <Spin />
            </div>
          ) : shots.length === 0 ? (
            <Empty description="暂无分镜" />
          ) : (
            <List
              size="small"
              dataSource={shots}
              renderItem={(item) => {
                const active = item.id === selectedId
                return (
                  <List.Item
                    onClick={() => setSelectedId(item.id)}
                    style={{
                      cursor: 'pointer',
                      padding: '8px 10px',
                      borderRadius: 8,
                      background: active ? 'rgba(22, 119, 255, 0.08)' : 'transparent',
                    }}
                  >
                    <div className="min-w-0 w-full">
                      <div className="flex items-center justify-between gap-2">
                        <div className="truncate font-medium">{`#${item.index} ${item.title ?? ''}`}</div>
                      </div>
                      <div className="text-xs text-gray-500 truncate mt-0.5">{item.script_excerpt ?? ''}</div>
                    </div>
                  </List.Item>
                )
              }}
            />
          )}
        </div>

        <div className="flex-1 min-w-0 overflow-auto">
          {!selectedShot || !draft ? (
            <Empty description="请选择一个分镜" />
          ) : (
            <div className="space-y-3">
              <Space wrap>
                <div className="text-sm text-gray-600">{`镜头 #${selectedShot.index}`}</div>
                <Select<ShotStatus | undefined>
                  value={draft.status}
                  style={{ width: 160 }}
                  placeholder="状态"
                  allowClear
                  options={[
                    { label: 'pending', value: 'pending' },
                    { label: 'generating', value: 'generating' },
                    { label: 'ready', value: 'ready' },
                  ]}
                  onChange={(v) => setDraft((p) => (p ? { ...p, status: v } : p))}
                />
                <Button type="primary" disabled={!dirty} loading={saving} onClick={() => void save()}>
                  保存
                </Button>
                <Button disabled={!dirty || saving} onClick={cancel}>
                  取消
                </Button>
              </Space>

              <div>
                <div className="text-sm text-gray-600 mb-1">标题</div>
                <Input
                  value={draft.title}
                  onChange={(e) => setDraft((p) => (p ? { ...p, title: e.target.value } : p))}
                />
              </div>

              <div>
                <div className="text-sm text-gray-600 mb-1">内容</div>
                <TextArea
                  value={draft.script_excerpt}
                  rows={16}
                  onChange={(e) => setDraft((p) => (p ? { ...p, script_excerpt: e.target.value } : p))}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </Card>
  )
}

