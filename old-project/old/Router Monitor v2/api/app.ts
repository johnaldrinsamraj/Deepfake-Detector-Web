import express, { type NextFunction, type Request, type Response } from 'express'
import cors from 'cors'
import { existsSync } from 'fs'
import path from 'path'
import dotenv from 'dotenv'
import { fileURLToPath } from 'url'
import { monitorService } from './services/monitorService.js'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const projectRoot = path.resolve(__dirname, '..')
const distPath = path.join(projectRoot, 'dist')

dotenv.config()

const app: express.Application = express()

app.use(cors())
app.use(express.json({ limit: '10mb' }))
app.use(express.urlencoded({ extended: true, limit: '10mb' }))

function asyncHandler(
  handler: (req: Request, res: Response, next: NextFunction) => Promise<void>,
) {
  return (req: Request, res: Response, next: NextFunction) => {
    void handler(req, res, next).catch(next)
  }
}

app.get('/api/health', (_req, res) => {
  res.status(200).json({ success: true, message: 'ok' })
})

app.get(
  '/api/overview',
  asyncHandler(async (_req, res) => {
    res.json(await monitorService.getOverview())
  }),
)

app.get(
  '/api/usage/live',
  asyncHandler(async (req, res) => {
    const limit = Number(req.query.limit ?? 40)
    res.json(await monitorService.getLiveUsage(limit))
  }),
)

app.get(
  '/api/usage/history',
  asyncHandler(async (req, res) => {
    const range = typeof req.query.range === 'string' ? req.query.range : '24h'
    res.json(await monitorService.getUsageHistory(range))
  }),
)

app.get(
  '/api/devices',
  asyncHandler(async (_req, res) => {
    res.json(await monitorService.getDevices())
  }),
)

app.post(
  '/api/devices/nickname',
  asyncHandler(async (req, res) => {
    res.json(await monitorService.setNickname(req.body))
  }),
)

app.post(
  '/api/devices/disconnect',
  asyncHandler(async (req, res) => {
    res.json(await monitorService.disconnectDevice(req.body))
  }),
)

app.post(
  '/api/devices/ban',
  asyncHandler(async (req, res) => {
    res.json(await monitorService.banDevice(req.body))
  }),
)

app.post(
  '/api/devices/unban',
  asyncHandler(async (req, res) => {
    res.json(await monitorService.unbanDevice(req.body))
  }),
)

app.get(
  '/api/settings',
  asyncHandler(async (_req, res) => {
    res.json(await monitorService.getSettings())
  }),
)

app.post(
  '/api/settings',
  asyncHandler(async (req, res) => {
    res.json(await monitorService.updateSettings(req.body))
  }),
)

app.post(
  '/api/router/test',
  asyncHandler(async (req, res) => {
    res.json(await monitorService.testRouter(req.body))
  }),
)

if (existsSync(distPath)) {
  app.use(express.static(distPath))

  app.get('*', (req, res, next) => {
    if (req.path.startsWith('/api/')) {
      next()
      return
    }

    res.sendFile(path.join(distPath, 'index.html'))
  })
}

app.use((error: Error, req: Request, res: Response) => {
  res.status(500).json({
    success: false,
    error: error.message || 'Server internal error',
  })
})

app.use((req: Request, res: Response) => {
  res.status(404).json({
    success: false,
    error: 'API not found',
  })
})

export default app
