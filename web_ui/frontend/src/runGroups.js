const DEFAULT_GROUP_NAME = '混沌'

export const buildDisplayGroups = (groups) => {
  const defaultGroups = groups.filter(group => group.name === DEFAULT_GROUP_NAME)
  const otherGroups = groups.filter(group => group.name !== DEFAULT_GROUP_NAME)
  if (defaultGroups.length === 0) {
    return otherGroups.map(group => ({ ...group, ids: [group.id] }))
  }
  return [
    { ...defaultGroups[0], ids: defaultGroups.map(group => group.id), isDefault: true },
    ...otherGroups.map(group => ({ ...group, ids: [group.id] })),
  ]
}
