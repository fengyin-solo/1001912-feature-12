import { defineStore } from 'pinia'

import { fetchJson } from '@/api/client'

export type TeamInfo = { name: string; members: string[] }

type TeamsPayload = { teams: TeamInfo[]; admin: string }

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '值班管理员',
    shiftLabel: '白班 08:00-20:00',
    scope: '风电场机组运维平台',
    teams: [] as TeamInfo[],
    adminName: '值班管理员',
    teamsLoaded: false,
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
    /** 当前操作人所属班组；值班管理员不属于任何运维班组。 */
    currentTeam(state): string | null {
      if (state.operator === state.adminName) {
        return null
      }
      const found = state.teams.find((team) => team.members.includes(state.operator))
      return found ? found.name : null
    },
    isAdmin(): (operator?: string) => boolean {
      return (operator?: string) => (operator ?? this.operator) === this.adminName
    },
  },
  actions: {
    async ensureTeams(force = false) {
      if (this.teamsLoaded && !force) {
        return
      }
      const payload = await fetchJson<TeamsPayload>('/api/collector/teams')
      this.teams = payload.teams
      this.adminName = payload.admin
      this.teamsLoaded = true
    },
    setOperator(operator: string) {
      this.operator = operator
    },
    setShift(label: string) {
      this.shiftLabel = label
    },
  },
})
