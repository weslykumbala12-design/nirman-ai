import axios from 'axios'

const api = axios.create({ baseURL: '/api/v1' })

export const uploadPhotos = (buildingId, files, prompts, hints) => {
  const fd = new FormData()
  files.forEach(f => fd.append('files', f))
  prompts.forEach(p => fd.append('prompts', p))
  hints.forEach(h => fd.append('hints', h))
  return api.post(`/buildings/${buildingId}/upload-photos`, fd)
}

export const generateBuilding = (buildingId, userRequest, useBestOfN = true) =>
  api.post(`/buildings/${buildingId}/generate`, {
    user_request: userRequest,
    use_best_of_n: useBestOfN,
  })

export const listAttempts = (buildingId) =>
  api.get(`/buildings/${buildingId}/attempts`)

export const getAttempt = (buildingId, attemptId) =>
  api.get(`/buildings/${buildingId}/attempts/${attemptId}`)

export const submitFeedback = (buildingId, attemptId, feedback, accepted) =>
  api.post(`/buildings/${buildingId}/attempts/${attemptId}/feedback`, {
    feedback, accepted,
  })

export const getGraph = (buildingId) =>
  api.get(`/buildings/${buildingId}/graph`)

export const getFailurePatterns = (buildingId) =>
  api.get(`/buildings/${buildingId}/failure-patterns`)

export const getBanditStats = () =>
  api.get('/bandit/stats')

export const gltfUrl = (attemptId, buildingId) =>
  `/api/v1/buildings/${buildingId}/attempts/${attemptId}/gltf`

export default api
