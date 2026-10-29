<script lang="ts">
  let {
    kind = 'user',
    initials = '',
    tone = '',
    size = '',
    me = false,
    talking = false,
    muted = false,
    away = false,
    title = '',
    arrive = false,
  }: {
    kind?: string
    initials?: string
    tone?: string
    size?: '' | 's' | 'xs'
    me?: boolean
    talking?: boolean
    muted?: boolean
    away?: boolean
    title?: string
    arrive?: boolean
  } = $props()
</script>

<span
  class="av {size}"
  class:guest={kind === 'guest'}
  class:agent={kind === 'agent'}
  class:me
  class:talking
  class:muted
  class:away
  class:arrive
  style={tone && kind === 'user' ? `--tone:${tone}` : undefined}
  title={title || undefined}
  role={title ? 'img' : undefined}
  aria-label={title || undefined}>{size === 'xs' ? '' : initials}</span>
