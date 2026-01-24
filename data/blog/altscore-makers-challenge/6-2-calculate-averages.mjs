import { readFileSync } from 'fs'

const csvContent = readFileSync('6-pokemon-heights.csv', 'utf-8')
const lines = csvContent.trim().split('\n')

const typeData = new Map()

for (const line of lines) {
  const [, , type, height] = line.split(':')
  const heightNum = parseFloat(height)

  if (!typeData.has(type)) {
    typeData.set(type, { sum: 0, count: 0 })
  }

  const data = typeData.get(type)
  data.sum += heightNum
  data.count += 1
}

// Calculate averages and format the result
const heights = {}
for (const [type, data] of typeData) {
  const average = (data.sum / data.count).toFixed(3)
  heights[type] = average
}

// Output the result
console.log(JSON.stringify({ heights }, null, 2))
