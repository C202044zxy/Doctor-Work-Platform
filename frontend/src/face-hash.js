// §2 冲突 1 方案 A / §4.3.3【校验】：人脸 Mock 不能"非空即通过"——那样验收判据⑤
//「换人脸不通过」永远满足不了。这里真的做一次图像特征提取与比对：8×8 dHash +
// 汉明距离，和 D 在服务端 `MockFaceAuthProvider` 里要写的是同一套算法。
//
// 因此"只替换外部调用"的边界落在比对之后：真正的人脸特征向量与活体检测属于
// 腾讯云人脸核身，这里替代的是那一次网络请求，不是比对本身。

export const HASH_BITS = 64
export const MAX_DISTANCE = 20 // §2 冲突 1：阈值放宽到 20，缓解同人多张照片的误拒

// 9×8：横向相邻像素两两比较得到 8×8 = 64 位，多出的一列是右邻居。
function draw(source) {
  const canvas = document.createElement('canvas')
  canvas.width = 9
  canvas.height = 8
  const context = canvas.getContext('2d', { willReadFrequently: true })
  context.drawImage(source, 0, 0, 9, 8)
  return context.getImageData(0, 0, 9, 8).data
}

function grey(data, offset) {
  return 0.299 * data[offset] + 0.587 * data[offset + 1] + 0.114 * data[offset + 2]
}

// Bit order is row-major, left to right; only relative distance matters, so the
// exact packing is free as long as both sides agree.
export function hashSource(source) {
  const data = draw(source)
  let bits = ''
  for (let y = 0; y < 8; y += 1) {
    for (let x = 0; x < 8; x += 1) {
      const offset = (y * 9 + x) * 4
      bits += grey(data, offset) > grey(data, offset + 4) ? '1' : '0'
    }
  }
  return bits
}

export async function hashBlob(blob) {
  const bitmap = await createImageBitmap(blob)
  try {
    return hashSource(bitmap)
  } finally {
    bitmap.close?.()
  }
}

export function hashDistance(a, b) {
  // A missing or mismatched hash can never be "close enough" — fail closed.
  if (!a || !b || a.length !== b.length) return HASH_BITS
  let count = 0
  for (let index = 0; index < a.length; index += 1) if (a[index] !== b[index]) count += 1
  return count
}
