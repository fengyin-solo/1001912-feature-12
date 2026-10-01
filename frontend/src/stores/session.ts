import { defineStore } from 'pinia'

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '值班管理员',
    shiftLabel: '白班 08:00-20:00',
    scope: '风电场机组运维平台',
    // 集电线路按班组收口：当前登录的班组与成员，进入集电线路页时可切换。
    collectorTeam: '输电一班',
    collectorOperator: '张伟',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setCollectorIdentity(team: string, operator: string) {
      this.collectorTeam = team
      this.collectorOperator = operator
    },
  },
})
