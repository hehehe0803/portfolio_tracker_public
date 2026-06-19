'use client'

import { useCallback, useEffect, useState } from 'react'
import { intelligenceAPI, type EntityType, type Note } from '@/lib/api'

export function NotePanel({ entityType, entityId, title = 'Notes' }: { entityType: EntityType; entityId: string; title?: string }) {
  const [notes, setNotes] = useState<Note[]>([])
  const [content, setContent] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editContent, setEditContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setNotes(await intelligenceAPI.listNotes({ entity_type: entityType, entity_id: entityId }))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Notes failed to load')
    } finally {
      setLoading(false)
    }
  }, [entityType, entityId])

  useEffect(() => {
    void load()
  }, [load])

  async function createNote() {
    const trimmed = content.trim()
    if (!trimmed) return
    setSaving(true)
    setError('')
    try {
      await intelligenceAPI.createNote({ entity_type: entityType, entity_id: entityId, content: trimmed })
      setContent('')
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Note save failed')
    } finally {
      setSaving(false)
    }
  }

  async function updateNote() {
    const trimmed = editContent.trim()
    if (editingId == null || !trimmed) return
    setSaving(true)
    setError('')
    try {
      await intelligenceAPI.updateNote(editingId, trimmed)
      setEditingId(null)
      setEditContent('')
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Note update failed')
    } finally {
      setSaving(false)
    }
  }

  async function deleteNote(id: number) {
    setError('')
    try {
      await intelligenceAPI.deleteNote(id)
      setNotes(current => current.filter(note => note.id !== id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Note delete failed')
    }
  }

  return (
    <div className="panel" style={{ padding: 20 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
        <div className="panel-header">{title}</div>
        <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)' }}>
          {notes.length} saved
        </span>
      </div>
      <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        <textarea
          value={content}
          onChange={event => setContent(event.target.value)}
          placeholder={`Add a ${entityType} note…`}
          rows={3}
          style={{ flex: 1, background: 'var(--bg-inset)', border: '1px solid var(--line-2)', color: 'var(--fg-0)', padding: 10, fontSize: 12, resize: 'vertical' }}
        />
        <button type="button" className="btn-ghost" disabled={saving || !content.trim()} onClick={createNote}>
          {saving ? 'Saving…' : 'Add'}
        </button>
      </div>
      {error ? <div style={{ marginTop: 8, color: 'var(--pl-dn)', fontSize: 11.5 }}>{error}</div> : null}
      <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
        {loading ? (
          <div style={{ color: 'var(--fg-3)', fontSize: 11.5 }}>Loading notes…</div>
        ) : notes.length === 0 ? (
          <div style={{ color: 'var(--fg-3)', fontSize: 11.5 }}>No notes yet.</div>
        ) : (
          notes.map(note => (
            <div key={note.id} style={{ borderTop: '1px solid var(--line-1)', paddingTop: 10 }}>
              {editingId === note.id ? (
                <div style={{ display: 'grid', gap: 8 }}>
                  <textarea
                    value={editContent}
                    onChange={event => setEditContent(event.target.value)}
                    aria-label="Edit note"
                    rows={3}
                    style={{ background: 'var(--bg-inset)', border: '1px solid var(--line-2)', color: 'var(--fg-0)', padding: 10, fontSize: 12, resize: 'vertical' }}
                  />
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button type="button" className="btn-ghost" onClick={() => void updateNote()} disabled={saving || !editContent.trim()} style={{ fontSize: 10, padding: '3px 7px' }}>
                      Save
                    </button>
                    <button type="button" className="btn-ghost" onClick={() => { setEditingId(null); setEditContent('') }} style={{ fontSize: 10, padding: '3px 7px' }}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div style={{ whiteSpace: 'pre-wrap', fontSize: 12, color: 'var(--fg-1)', lineHeight: 1.6 }}>{note.content}</div>
                  <div style={{ marginTop: 7, display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                    <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10, color: 'var(--fg-3)' }}>
                      {new Date(note.created_at).toISOString().slice(0, 16).replace('T', ' ')}
                    </span>
                    <span style={{ display: 'flex', gap: 6 }}>
                      <button type="button" className="btn-ghost" onClick={() => { setEditingId(note.id); setEditContent(note.content) }} style={{ fontSize: 10, padding: '3px 7px' }}>
                        Edit
                      </button>
                      <button type="button" className="btn-ghost" onClick={() => void deleteNote(note.id)} style={{ fontSize: 10, padding: '3px 7px' }}>
                        Delete
                      </button>
                    </span>
                  </div>
                </>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
