const API_KEY = 'API-KEY'
const URL = 'https://makers-challenge.altscore.ai/v1/s1/e8/actions/door'

async function makeRequest(currentCookie = '') {
  try {
    const headers = {
      accept: 'application/json',
      'API-KEY': API_KEY,
    }

    if (currentCookie) {
      headers.Cookie = `gryffindor=${currentCookie}`
    }

    const response = await fetch(URL, {
      method: 'POST',
      headers,
      body: '',
    })

    console.log('\nCurrent cookie:', currentCookie)

    // Check if we've reached the end, got this value from testing in the swagger UI
    const data = await response.text()
    if (data.includes('Has llegado al final')) {
      return { finished: true }
    }

    // Extract new cookie from Set-Cookie header
    const setCookieHeader = response.headers.get('set-cookie')
    let newCookie = ''

    if (setCookieHeader) {
      const match = setCookieHeader.match(/gryffindor=["]*([^";]*)["]*/)
      if (match) {
        newCookie = match[1]
      }
    }

    console.log('New cookie:', newCookie)

    if (newCookie) {
      console.log('Got new cookie value:', newCookie)
      return { finished: false, newCookie }
    }

    return { finished: true }
  } catch (error) {
    console.error('Error making request:', error.message)
    return { finished: true }
  }
}

async function collectCookies() {
  console.log('Collecting cookies...')
  let currentCookie = ''
  let cookieValues = []
  let finished = false

  while (!finished) {
    const result = await makeRequest(currentCookie)

    if (result.finished) {
      finished = true
    } else if (result.newCookie) {
      currentCookie = result.newCookie
      cookieValues.push(result.newCookie)
    }

    await new Promise((resolve) => setTimeout(resolve, 1000))
  }

  const cookieString = cookieValues.join(' ')
  console.log('All cookie values:', cookieString)

  console.log('Decoding message...')
  try {
    // TODO: fix This is not decoding the entire string, just the first word for some reason
    const decodedMessage = Buffer.from(cookieString, 'base64').toString('utf-8')
    console.log('Decoded message:', decodedMessage)
  } catch (error) {
    console.error('Error decoding message:', error.message)
  }
}

collectCookies()
