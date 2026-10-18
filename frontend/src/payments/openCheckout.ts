// src/payments/openCheckout.ts
import { client } from '../api/client';

declare global {
  interface Window {
    Razorpay: any;
  }
}

export type Checkout = {
  payment_id: string;
  key_id: string;
  order_id: string;
  amount_minor: number;
  currency: string;
  description: string;
  expires_at: string;
};

const loadCheckout = () =>
  new Promise<void>((resolve, reject) => {
    if (typeof window === 'undefined') return resolve();
    if (window.Razorpay) return resolve();
    const s = document.createElement('script');
    s.src = 'https://checkout.razorpay.com/v1/checkout.js';
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('CHECKOUT_LOAD_FAILED'));
    document.body.appendChild(s);
  });

/** Resolves with the server's verify response, or 'DISMISSED' when the user closes the window. */
export async function openCheckout(c: Checkout, me: { name: string; email: string }) {
  await loadCheckout();
  return new Promise<any>((resolve) => {
    if (!window.Razorpay) {
      // Mock / fallback environment
      resolve({ ok: false, error: 'CHECKOUT_UNAVAILABLE' });
      return;
    }
    const rzp = new window.Razorpay({
      key: c.key_id,
      order_id: c.order_id,
      amount: c.amount_minor,
      currency: c.currency,
      name: 'GymPro',
      description: c.description,
      prefill: { name: me.name, email: me.email },
      handler: async (resp: {
        razorpay_payment_id: string;
        razorpay_order_id: string;
        razorpay_signature: string;
      }) => {
        try {
          const res = await client.post('/payments/razorpay/verify', resp);
          resolve(res.data);
        } catch (e: any) {
          resolve({ ok: false, error: e?.response?.data?.detail?.error || 'PAYMENT_VERIFICATION_FAILED' });
        }
      },
      modal: {
        ondismiss: () => resolve('DISMISSED'),
        escape: false,
      },
    });
    rzp.open();
  });
}
